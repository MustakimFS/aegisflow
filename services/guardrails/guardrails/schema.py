"""JSON Schema validation. Cached compiled validators per schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


class SchemaCache:
    def __init__(self, capacity: int = 256) -> None:
        self._cache: dict[str, Draft202012Validator] = {}
        self._capacity = capacity

    def validator(self, schema: dict[str, Any]) -> Draft202012Validator:
        key = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        v = self._cache.get(key)
        if v is None:
            v = Draft202012Validator(schema)
            if len(self._cache) >= self._capacity:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = v
        return v


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]


def validate(value: object, schema: dict[str, Any], cache: SchemaCache) -> ValidationResult:
    validator = cache.validator(schema)
    errors: list[ValidationError] = list(validator.iter_errors(value))
    if not errors:
        return ValidationResult(ok=True, errors=[])
    return ValidationResult(
        ok=False,
        errors=[f"{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors],
    )
