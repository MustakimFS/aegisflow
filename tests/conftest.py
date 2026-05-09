"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def jwt_secret() -> str:
    return "devonly_change_me"
