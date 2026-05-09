"""JSON repair edge cases."""

from __future__ import annotations

import pytest
from guardrails.json_repair import RepairFailed, repair


def test_passes_through_valid_json() -> None:
    r = repair('{"a": 1}')
    assert r.parsed == {"a": 1}
    assert r.was_repaired is False


def test_strips_code_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    r = repair(raw)
    assert r.parsed == {"a": 1}
    assert "stripped_code_fence" in r.repairs


def test_strips_prose_prefix() -> None:
    raw = 'Here is the JSON you requested: {"a": 1}'
    r = repair(raw)
    assert r.parsed == {"a": 1}
    assert "stripped_prose_prefix" in r.repairs


def test_strips_trailing_text() -> None:
    raw = '{"a": 1} (hope this helps!)'
    r = repair(raw)
    assert r.parsed == {"a": 1}
    assert "stripped_trailing_text" in r.repairs


def test_removes_trailing_commas() -> None:
    raw = '{"a": 1, "b": [1, 2, 3,],}'
    r = repair(raw)
    assert r.parsed == {"a": 1, "b": [1, 2, 3]}


def test_balances_curlies() -> None:
    raw = '{"a": {"b": 1}'
    r = repair(raw)
    assert r.parsed == {"a": {"b": 1}}
    assert "balanced_curlies" in r.repairs


def test_unrepairable_raises() -> None:
    raw = "this is not json at all, just prose."
    with pytest.raises(RepairFailed):
        repair(raw)


def test_converts_single_quotes_when_no_double() -> None:
    raw = "{'a': 1}"
    r = repair(raw)
    assert r.parsed == {"a": 1}
