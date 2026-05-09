"""Best-effort JSON repair.

LLMs love to:
  - leave trailing commas,
  - drop closing braces / brackets,
  - emit single quotes instead of double quotes,
  - wrap output in ``` fences,
  - prepend explanatory prose before the JSON object.

We never *guess* values - repairs only adjust structure. If the result still
doesn't parse, we surface a `RepairFailed` rather than silently lying.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


class RepairFailed(Exception):
    pass


@dataclass(frozen=True)
class RepairResult:
    parsed: object
    was_repaired: bool
    repairs: tuple[str, ...]


_FENCE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def repair(raw: str) -> RepairResult:
    """Attempt to parse `raw` as JSON, applying conservative repairs as needed."""
    repairs: list[str] = []

    # First, fast-path: maybe it's already valid.
    try:
        return RepairResult(parsed=json.loads(raw), was_repaired=False, repairs=())
    except json.JSONDecodeError:
        pass

    text = raw.strip()

    fence_match = _FENCE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()
        repairs.append("stripped_code_fence")

    # Strip text before the first { or [
    obj_start = _find_outer_object(text)
    if obj_start > 0:
        text = text[obj_start:]
        repairs.append("stripped_prose_prefix")

    # Strip trailing junk after the last balanced } or ]
    obj_end = _find_outer_close(text)
    if obj_end is not None and obj_end < len(text) - 1:
        text = text[: obj_end + 1]
        repairs.append("stripped_trailing_text")

    # Trailing commas before } or ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", text)
    if cleaned != text:
        repairs.append("removed_trailing_commas")
        text = cleaned

    # Single → double quotes (only when keys / values aren't already mixed)
    if "'" in text and '"' not in text:
        text = text.replace("'", '"')
        repairs.append("converted_single_quotes")

    # Best-effort closing-bracket balancing
    open_curly = text.count("{")
    close_curly = text.count("}")
    if open_curly > close_curly:
        text = text + "}" * (open_curly - close_curly)
        repairs.append("balanced_curlies")
    open_sq = text.count("[")
    close_sq = text.count("]")
    if open_sq > close_sq:
        text = text + "]" * (open_sq - close_sq)
        repairs.append("balanced_brackets")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepairFailed(f"unrepairable JSON: {exc}") from exc

    return RepairResult(parsed=parsed, was_repaired=True, repairs=tuple(repairs))


def _find_outer_object(text: str) -> int:
    for i, ch in enumerate(text):
        if ch in "{[":
            return i
    return 0


def _find_outer_close(text: str) -> int | None:
    """Track bracket depth to find the matching close of the first opening bracket."""
    depth = 0
    in_string = False
    escape = False
    start: int | None = None
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            if start is None:
                start = i
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0 and start is not None:
                return i
    return None
