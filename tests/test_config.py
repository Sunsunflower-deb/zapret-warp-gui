"""Тесты конфига: дефолты, слияние, миграция, битый файл."""
import json

from core import config


def test_defaults_are_sane(settings):
    assert settings["strategy"] == "warp_simple_fake.bat"
    assert settings["fooling"] == "auto"
    assert settings["warp_masque"] == "h2-only"


def test_load_merges_file(config_path):
    config_path.write_text(
        json.dumps({"strategy": "general_simple_fake.bat", "custom": 1}),
        encoding="utf-8",
    )
    cfg = config.load()
    assert cfg["strategy"] == "general_simple_fake.bat"
    assert cfg["custom"] == 1
    # ключи, которых нет в файле, берутся из дефолтов
    assert cfg["fooling"] == "auto"


def test_load_broken_json(config_path):
    config_path.write_text("{not json", encoding="utf-8")
    cfg = config.load()
    assert cfg["fooling"] == "auto"


def test_load_non_dict_json(config_path):
    config_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert config.load()["fooling"] == "auto"


def test_save_roundtrip(config_path):
    cfg = config.load()
    cfg["fooling"] = "ts"
    config.save(cfg)
    assert config.load()["fooling"] == "ts"


def test_save_is_utf8_and_readable(config_path):
    cfg = config.load()
    cfg["warp_user"] = "пользователь"
    config.save(cfg)
    raw = config_path.read_text(encoding="utf-8")
    assert "пользователь" in raw
    assert json.loads(raw)["warp_user"] == "пользователь"


def test_saved_config_is_stable(config_path):
    """Повторное сохранение не должно ничего менять (нет «дрейфа» ключей)."""
    cfg = config.load()
    config.save(cfg)
    first = config_path.read_text(encoding="utf-8")
    config.save(config.load())
    assert config_path.read_text(encoding="utf-8") == first
