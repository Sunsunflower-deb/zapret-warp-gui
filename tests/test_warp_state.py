"""Тесты разбора `warp-cli status` в enum.

Регресс-защита: раньше состояние определялось подстрокой `"Connected" in st`,
и любой незнакомый формат вывода молча становился «отключен», а «Reconnecting»
не отличался от «Connected».
"""
import pytest

from core import warp

CASES = [
    ("Status update: Connected\nNetwork: healthy", warp.WarpState.CONNECTED, "Connected"),
    ("Status update: Disconnected", warp.WarpState.DISCONNECTED, "Disconnected"),
    ("Status update: Connecting", warp.WarpState.CONNECTING, "Connecting"),
    ("Status update: Disconnecting", warp.WarpState.DISCONNECTING, "Disconnecting"),
    ("Status update: Reconnecting", warp.WarpState.CONNECTING, "Reconnecting"),
    ("Status update: Registration missing", warp.WarpState.NO_REGISTRATION,
     "Registration missing"),
    ("Connected", warp.WarpState.CONNECTED, "Connected"),
    ("", warp.WarpState.UNKNOWN, ""),
    ("какой-то новый формат", warp.WarpState.UNKNOWN, "какой-то новый формат"),
]


@pytest.mark.parametrize("raw,expected,line", CASES)
def test_parse_status(raw, expected, line):
    got, got_line = warp.parse_status(raw)
    assert got is expected
    assert got_line == line


def test_disconnected_is_not_connected():
    """Классическая ловушка: "Disconnected" содержит "connected"."""
    assert warp.parse_status("Status update: Disconnected")[0] is not warp.WarpState.CONNECTED


def test_disconnecting_is_not_connecting():
    state, _ = warp.parse_status("Status update: Disconnecting")
    assert state is warp.WarpState.DISCONNECTING


def test_state_uses_status(monkeypatch):
    monkeypatch.setattr(warp, "status", lambda cfg: "Status update: Connected")
    state, line = warp.state({})
    assert state is warp.WarpState.CONNECTED
    assert line == "Connected"


def test_state_survives_empty_status(monkeypatch):
    monkeypatch.setattr(warp, "status", lambda cfg: "")
    assert warp.state({})[0] is warp.WarpState.UNKNOWN


# --- apply_settings -------------------------------------------------------

class _Result:
    def __init__(self, code=0, out="", err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def test_apply_settings_collects_errors(monkeypatch):
    calls = []

    def fake_run(cfg, *args):
        calls.append(args)
        # masque-options не поддерживается «старой» версией
        if "masque-options" in args:
            return _Result(1, err="unknown command")
        return _Result(0)

    monkeypatch.setattr(warp, "run", fake_run)
    errors = warp.apply_settings({"warp_mode": "warp", "warp_masque": "h2-only"})
    assert len(errors) == 1
    assert errors[0][0] == "masque"
    assert "unknown command" in errors[0][1]
    assert any("mode" in c for c in calls)


def test_apply_settings_all_ok(monkeypatch):
    monkeypatch.setattr(warp, "run", lambda cfg, *a: _Result(0))
    assert warp.apply_settings({}) == []


def test_apply_settings_endpoint_set_error(monkeypatch):
    def fake_run(cfg, *args):
        return _Result(1, err="bad endpoint") if "endpoint" in args else _Result(0)

    monkeypatch.setattr(warp, "run", fake_run)
    errors = warp.apply_settings({"warp_endpoint": "1.2.3.4:443"})
    assert [e[0] for e in errors] == ["endpoint"]


def test_connect_raises_on_registration_missing(monkeypatch):
    monkeypatch.setattr(warp, "run", lambda cfg, *a: _Result(0))
    monkeypatch.setattr(warp.time, "sleep", lambda s: None)
    monkeypatch.setattr(warp, "state",
                        lambda cfg: (warp.WarpState.NO_REGISTRATION, "Registration missing"))
    with pytest.raises(RuntimeError) as exc:
        warp.connect({})
    assert "не зарегистрирован" in str(exc.value)


def test_connect_returns_line_when_connected(monkeypatch):
    monkeypatch.setattr(warp, "run", lambda cfg, *a: _Result(0))
    monkeypatch.setattr(warp.time, "sleep", lambda s: None)
    monkeypatch.setattr(warp, "state", lambda cfg: (warp.WarpState.CONNECTED, "Connected"))
    assert warp.connect({}) == "Connected"


def test_connect_reports_last_state(monkeypatch):
    monkeypatch.setattr(warp, "run", lambda cfg, *a: _Result(0))
    monkeypatch.setattr(warp.time, "sleep", lambda s: None)
    monkeypatch.setattr(warp, "state",
                        lambda cfg: (warp.WarpState.CONNECTING, "Connecting"))
    # deadline считается один раз, затем условие цикла проверяется дважды:
    # первый раз — заходим в тело, второй — выходим по истечении времени
    ticks = iter([0.0, 0.0, 100.0])
    monkeypatch.setattr(warp.time, "time", lambda: next(ticks))
    with pytest.raises(RuntimeError) as exc:
        warp.connect({}, timeout=2)
    assert "Connecting" in str(exc.value)
