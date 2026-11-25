"""Тесты состояния приложения и фонового монитора."""
import time

from core import probe, state, warp


def _reach(name="YouTube", ok=True, kind="ok", rtt=100.0):
    return state.Reachability(name, ok, kind, rtt)


def test_appstate_healthy():
    good = state.AppState(engine_running=True,
                          warp_state=warp.WarpState.CONNECTED,
                          reachability=(_reach("a", True), _reach("b", True)))
    assert good.healthy is True

    no_engine = state.AppState(engine_running=False,
                               warp_state=warp.WarpState.CONNECTED,
                               reachability=(_reach(),))
    assert no_engine.healthy is False

    no_warp = state.AppState(engine_running=True,
                             warp_state=warp.WarpState.DISCONNECTED,
                             reachability=(_reach(),))
    assert no_warp.healthy is False


def test_appstate_healthy_needs_half_of_probes():
    half = state.AppState(engine_running=True, warp_state=warp.WarpState.CONNECTED,
                          reachability=(_reach("a", True), _reach("b", False)))
    assert half.healthy is True
    minority = state.AppState(engine_running=True, warp_state=warp.WarpState.CONNECTED,
                              reachability=(_reach("a", True), _reach("b", False),
                                            _reach("c", False)))
    assert minority.healthy is False


def test_healthy_ignores_warp_when_disabled():
    """Если WARP выключен в конфиге, требовать туннель нельзя."""
    st = state.AppState(engine_running=True, warp_enabled=False,
                        warp_state=warp.WarpState.DISCONNECTED,
                        reachability=(_reach("a", True),))
    assert st.healthy is True


def test_healthy_requires_warp_when_enabled():
    st = state.AppState(engine_running=True, warp_enabled=True,
                        warp_state=warp.WarpState.DISCONNECTED,
                        reachability=(_reach("a", True),))
    assert st.healthy is False


def test_collect_propagates_warp_enabled(monkeypatch, config_path):
    _patch_all(monkeypatch)
    st = state.collect({"warp_enabled": False}, do_probe=False)
    assert st.warp_enabled is False


def test_appstate_healthy_without_probes():
    st = state.AppState(engine_running=True, warp_state=warp.WarpState.CONNECTED)
    assert st.healthy is True


def test_appstate_leaks():
    st = state.AppState(reachability=(
        _reach("ok", True),
        _reach("tls", False, "tls_alert"),
        _reach("rst", False, "reset"),
        _reach("timeout", False, "timeout"),
    ))
    assert [r.name for r in st.leaks] == ["tls", "rst"]


def test_summary_lines():
    st = state.AppState(
        engine_running=True, engine_pid=4242, strategy="warp_simple_fake.bat",
        fooling="md5sig", warp_state=warp.WarpState.CONNECTED, warp_line="Connected",
        exit_ip="104.28.1.2", warp_flag="on", colo="FRA",
        reachability=(_reach("YouTube", True), _reach("Telegram", False, "timeout")),
        last_error="",
    )
    text = "\n".join(st.summary_lines())
    assert "запущен (pid 4242)" in text
    assert "warp_simple_fake.bat" in text
    assert "fooling: md5sig" in text
    assert "Connected" in text
    assert "104.28.1.2" in text
    assert "YouTube: [OK]" in text
    assert "Telegram: [!!]" in text


def test_summary_lines_with_error():
    st = state.AppState(last_error="trace: timeout")
    assert any("trace: timeout" in line for line in st.summary_lines())


def test_reachability_str():
    assert "[OK]" in str(_reach())
    assert "[!!]" in str(_reach(ok=False, kind="timeout"))


# --- collect --------------------------------------------------------------

def _patch_all(monkeypatch, warp_state=warp.WarpState.CONNECTED, running=True):
    monkeypatch.setattr(state.engine, "is_running", lambda: running)
    monkeypatch.setattr(state.engine, "desync_pid", lambda: 1234)
    monkeypatch.setattr(state.warp, "installed", lambda: True)
    monkeypatch.setattr(state.warp, "state", lambda cfg: (warp_state, warp_state.value))
    monkeypatch.setattr(
        state.probe, "probe_many",
        lambda targets=None, timeout=5.0: [(t, probe.ProbeResult(True, "ok", 12.0))
                                           for t in probe.DEFAULT_TARGETS],
    )
    monkeypatch.setattr(
        state.probe, "fetch_trace",
        lambda timeout=5.0: {"ip": "104.28.1.2", "colo": "FRA", "warp": "on", "rtt_ms": 9.0},
    )


def test_collect_fills_state(monkeypatch, config_path):
    _patch_all(monkeypatch)
    st = state.collect({"strategy": "warp_simple_fake.bat", "fooling": "auto"})
    assert st.engine_running is True
    assert st.engine_pid == 1234
    assert st.warp_connected is True
    assert st.exit_ip == "104.28.1.2"
    assert st.colo == "FRA"
    assert st.warp_flag == "on"
    assert len(st.reachability) == len(probe.DEFAULT_TARGETS)
    assert st.healthy is True
    assert st.last_error == ""


def test_collect_without_warp_installed(monkeypatch, config_path):
    _patch_all(monkeypatch)
    monkeypatch.setattr(state.warp, "installed", lambda: False)
    st = state.collect({}, do_probe=False)
    assert st.warp_state is warp.WarpState.UNKNOWN
    assert "warp-cli не установлен" in st.warp_line


def test_collect_no_probe_skips_network(monkeypatch, config_path):
    _patch_all(monkeypatch)
    monkeypatch.setattr(state.probe, "probe_many",
                        lambda *a, **k: __import__("pytest").fail("сеть не нужна"))
    st = state.collect({}, do_probe=False)
    assert st.reachability == ()
    assert st.exit_ip == ""


def test_collect_warp_state_exception(monkeypatch, config_path):
    _patch_all(monkeypatch)

    def boom(cfg):
        raise RuntimeError("warp-cli сломался")

    monkeypatch.setattr(state.warp, "state", boom)
    st = state.collect({}, do_probe=False)
    assert st.warp_state is warp.WarpState.UNKNOWN
    assert "warp-cli сломался" in st.last_error


# --- Monitor --------------------------------------------------------------

def test_monitor_tick_stores_state():
    mon = state.Monitor(collector=lambda: state.AppState(engine_running=True), interval=60)
    snapshot = mon.tick()
    assert snapshot.engine_running is True
    assert mon.last is snapshot
    assert mon.queue.get_nowait() is snapshot


def test_monitor_keeps_only_latest():
    counter = {"n": 0}

    def collector():
        counter["n"] += 1
        return state.AppState(engine_pid=counter["n"])

    mon = state.Monitor(collector=collector, interval=60)
    mon.tick()
    mon.tick()
    mon.tick()
    assert mon.queue.qsize() == 1
    assert mon.queue.get_nowait().engine_pid == 3


def test_monitor_survives_collector_exception():
    def boom():
        raise RuntimeError("сеть отвалилась")

    mon = state.Monitor(collector=boom, interval=60)
    snapshot = mon.tick()
    assert "сеть отвалилась" in snapshot.last_error


def test_monitor_background_thread():
    mon = state.Monitor(collector=lambda: state.AppState(engine_running=True), interval=1)
    mon.start()
    try:
        deadline = time.time() + 5
        snapshot = None
        while time.time() < deadline and snapshot is None:
            try:
                snapshot = mon.queue.get(timeout=0.2)
            except Exception:  # noqa: BLE001
                pass
        assert snapshot is not None and snapshot.engine_running is True
    finally:
        mon.stop()
    assert mon._thread is None
