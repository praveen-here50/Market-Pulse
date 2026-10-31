"""Shared test setup."""

import pytest

import database


@pytest.fixture(autouse=True)
def private_user_data(tmp_path, monkeypatch):
    """Point every test at an empty folder, so no test can touch real holdings."""
    folder = tmp_path / "user"
    monkeypatch.setattr(database, "DATA_FOLDER", folder)
    return folder


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    """Remove what api.py loaded from .env, so no test can use the owner's real key."""
    for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
