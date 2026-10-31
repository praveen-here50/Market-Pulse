"""Tests for settings.py. All values below are SYNTHETIC TEST DATA."""

import os

import pytest

import settings

NAME = "MARKETPULSE_TEST_SETTING"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.delenv(NAME, raising=False)
    yield
    os.environ.pop(NAME, None)


def write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_values_are_read(tmp_path):
    settings.load_env_file(write(tmp_path, f"{NAME}=abc\n"))
    assert os.environ[NAME] == "abc"


def test_spaces_and_a_windows_file_marker_are_ignored(tmp_path):
    settings.load_env_file(write(tmp_path, f"﻿{NAME} = abc  \n"))
    assert os.environ[NAME] == "abc"


def test_a_value_may_contain_an_equals_sign(tmp_path):
    settings.load_env_file(write(tmp_path, f"{NAME}=a=b\n"))
    assert os.environ[NAME] == "a=b"


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv(NAME, "from-environment")
    settings.load_env_file(write(tmp_path, f"{NAME}=from-file\n"))
    assert os.environ[NAME] == "from-environment"


def test_comments_and_blank_lines_are_skipped(tmp_path):
    settings.load_env_file(write(tmp_path, f"\n# {NAME}=hidden\n"))
    assert NAME not in os.environ


def test_a_missing_file_is_fine(tmp_path):
    settings.load_env_file(tmp_path / "missing.env")


def test_tests_cannot_see_the_real_key():
    assert "GEMINI_API_KEY" not in os.environ
