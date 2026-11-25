"""Тесты отчёта doctor: он должен печататься в любой консоли."""
import io
import sys

from core import doctor


def _report():
    return [
        ("bin/ (бинари)", "ok", "есть", ""),
        ("warp-cli (WARP)", "bad", "не найден", "установите WARP"),
        ("winws.log (хвост)", "warn", "…", ""),
    ]


def test_report_lists_statuses():
    text = doctor.format_report(_report(), unicode_icons=True)
    assert doctor.OK in text
    assert doctor.BAD in text
    assert doctor.WARN in text
    assert "warp-cli" in text


def test_report_ascii_fallback():
    """На cp1251-консоли эмодзи печатать нельзя — раньше это был UnicodeEncodeError."""
    text = doctor.format_report(_report(), unicode_icons=False)
    assert doctor.OK_ASCII in text
    assert doctor.BAD_ASCII in text
    text.encode("cp1251")  # не должно бросать


def test_report_ascii_is_default_for_narrow_stdout(monkeypatch):
    narrow = io.TextIOWrapper(io.BytesIO(), encoding="cp1251")
    monkeypatch.setattr(sys, "stdout", narrow)
    assert doctor._unicode_icons() is False
    text = doctor.format_report(_report())
    text.encode("cp1251")


def test_report_unicode_for_utf8_stdout(monkeypatch):
    wide = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", wide)
    assert doctor._unicode_icons() is True


def test_report_shows_fixes_only_for_bad():
    text = doctor.format_report(_report(), unicode_icons=False)
    assert "установите WARP" in text
    tail = text.split("Что нужно исправить:")[-1]
    assert "warp-cli" in tail
    assert "winws.log" not in tail


def test_report_all_ok():
    text = doctor.format_report([("a", "ok", "ok", "")], unicode_icons=False)
    assert "Все компоненты на месте" in text


def test_unknown_encoding_is_treated_as_narrow(monkeypatch):
    class Weird:
        encoding = "no-such-codec"

    monkeypatch.setattr(sys, "stdout", Weird())
    assert doctor._unicode_icons() is False
