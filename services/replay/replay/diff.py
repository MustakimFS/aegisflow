"""Compare two replay sequences. Used for regression testing across model versions."""

from __future__ import annotations

from typing import Any


def diff_runs(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk both sequences in lockstep and surface per-node differences.

    The replay walker is deliberately simple - it aligns by `(node_id, kind)`
    pairs in order. Out-of-order events show up as drift, which is itself
    information.
    """
    pairs = list(_align(left, right))
    drift: list[dict[str, Any]] = []
    same = 0
    for li, ri in pairs:
        if li is None or ri is None:
            drift.append({"left": li, "right": ri, "reason": "missing"})
            continue
        if li["payload"].get("output", {}).get("raw_text") != ri["payload"].get(
            "output", {}
        ).get("raw_text"):
            drift.append(
                {
                    "node_id": li["node_id"],
                    "left_confidence": li["payload"]
                    .get("reliability", {})
                    .get("confidence"),
                    "right_confidence": ri["payload"]
                    .get("reliability", {})
                    .get("confidence"),
                    "reason": "output_diverged",
                }
            )
        else:
            same += 1
    return {"matched": same, "drift": drift, "total_pairs": len(pairs)}


def _align(left: list[dict[str, Any]], right: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    li, ri = 0, 0
    while li < len(left) or ri < len(right):
        lv = left[li] if li < len(left) else None
        r = right[ri] if ri < len(right) else None
        if lv and r and (lv["node_id"], lv["kind"]) == (r["node_id"], r["kind"]):
            yield lv, r
            li += 1
            ri += 1
        elif lv and not r:
            yield lv, None
            li += 1
        elif r and not lv:
            yield None, r
            ri += 1
        else:
            yield lv, None
            yield None, r
            li += 1
            ri += 1
