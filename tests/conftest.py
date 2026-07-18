from __future__ import annotations

from pathlib import Path

import pytest

from nomnomcli.db import connect
from nomnomcli.foods import FoodRepository


@pytest.fixture
def user_db(tmp_path: Path) -> Path:
    return tmp_path / "user.sqlite3"


@pytest.fixture
def repository(user_db: Path):
    with connect(user_db) as connection:
        yield FoodRepository(connection)
