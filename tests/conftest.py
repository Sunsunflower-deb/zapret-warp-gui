"""Общие фикстуры тестов.

Тесты не должны трогать настоящий config.json рядом с приложением.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import config, paths  # noqa: E402


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    """Подменить путь к config.json на временный (файла ещё нет)."""
    target = tmp_path / "config.json"
    monkeypatch.setattr(paths, "CONFIG_PATH", str(target))
    return target


@pytest.fixture
def tmp_lists(tmp_path, monkeypatch):
    """Изолированный каталог списков: paths.APP_DIR/paths.LISTS_DIR -> tmp."""
    lists = tmp_path / "lists"
    lists.mkdir()
    monkeypatch.setattr(paths, "APP_DIR", str(tmp_path))
    monkeypatch.setattr(paths, "LISTS_DIR", str(lists))
    return lists


@pytest.fixture
def settings(config_path):
    """Свежий конфиг на дефолтах."""
    return config.load()
