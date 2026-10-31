"""Shared test setup."""

import pytest

import database


@pytest.fixture(autouse=True)
def private_user_data(tmp_path, monkeypatch):
    """Point every test at an empty folder, so no test can touch real holdings."""
    folder = tmp_path / "user"
    monkeypatch.setattr(database, "DATA_FOLDER", folder)
    return folder
