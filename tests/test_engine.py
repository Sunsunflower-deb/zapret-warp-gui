"""Тесты движка: fooling/timestamps, pidfile, права."""
import os

import pytest

from core import engine


class _Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_ensure_tcp_timestamps_noop_on_posix(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(
        engine.subprocess, "run",
        lambda *a, **k: pytest.fail("на Linux netsh вызываться не должен"),
    )
    assert engine.ensure_tcp_timestamps() is True


def test_ensure_tcp_timestamps_calls_netsh(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Done(0)

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(engine, "_nowin", lambda: {})
    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.ensure_tcp_timestamps() is True
    assert calls
    assert calls[0][:4] == ["netsh", "interface", "tcp", "set"]
    assert "timestamps=enabled" in calls[0]


def test_ensure_tcp_timestamps_reports_failure(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(engine, "_nowin", lambda: {})
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: _Done(1))
    assert engine.ensure_tcp_timestamps() is False


def test_ensure_tcp_timestamps_survives_missing_netsh(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(engine, "_nowin", lambda: {})

    def boom(*a, **k):
        raise FileNotFoundError("netsh")

    monkeypatch.setattr(engine.subprocess, "run", boom)
    assert engine.ensure_tcp_timestamps() is False


# --- pidfile --------------------------------------------------------------

def test_nfqws_pid_reads_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / "nfqws.pid"
    pidfile.write_text("12345\n", encoding="utf-8")
    monkeypatch.setattr(engine, "PIDFILE", str(pidfile))
    assert engine.nfqws_pid() == 12345


def test_nfqws_pid_garbage_and_missing(tmp_path, monkeypatch):
    pidfile = tmp_path / "nfqws.pid"
    pidfile.write_text("not-a-pid", encoding="utf-8")
    monkeypatch.setattr(engine, "PIDFILE", str(pidfile))
    assert engine.nfqws_pid() is None

    monkeypatch.setattr(engine, "PIDFILE", str(tmp_path / "absent.pid"))
    assert engine.nfqws_pid() is None


@pytest.mark.skipif(os.name == "nt", reason="os.kill(pid, 0) на Windows убивает процесс")
def test_pid_alive_for_self():
    assert engine._pid_alive(os.getpid()) is True


@pytest.mark.skipif(os.name == "nt", reason="os.kill(pid, 0) на Windows убивает процесс")
def test_pid_alive_for_dead_pid():
    # заведомо несуществующий PID
    assert engine._pid_alive(2 ** 22 + 12345) is False


def test_pid_alive_is_noop_on_windows(monkeypatch):
    """На Windows проверка через os.kill недопустима — она убивает процесс."""
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(
        engine.os, "kill",
        lambda *a, **k: pytest.fail("os.kill на Windows вызывать нельзя"),
    )
    assert engine._pid_alive(os.getpid()) is False


# --- hardening ------------------------------------------------------------

def _make_helper(tmp_path, mode):
    helper = tmp_path / "root-helper.sh"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(helper, mode)
    return helper


@pytest.mark.skipif(os.name == "nt", reason="POSIX-права не проверяются на Windows")
def test_helper_is_safe_for_ro_script(tmp_path, monkeypatch):
    helper = _make_helper(tmp_path, 0o755)
    monkeypatch.setattr(engine, "HELPER", str(helper))
    assert engine._helper_is_safe() is True


@pytest.mark.skipif(os.name == "nt", reason="POSIX-права не проверяются на Windows")
def test_helper_is_unsafe_when_group_writable(tmp_path, monkeypatch):
    helper = _make_helper(tmp_path, 0o775)
    monkeypatch.setattr(engine, "HELPER", str(helper))
    assert engine._helper_is_safe() is False


def test_helper_missing_is_unsafe(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "HELPER", str(tmp_path / "nope.sh"))
    assert engine._helper_is_safe() is False


def test_setup_root_refuses_on_windows(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(RuntimeError):
        engine.setup_root()


def test_is_running_uses_pidfile(tmp_path, monkeypatch):
    pidfile = tmp_path / "nfqws.pid"
    pidfile.write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(engine, "PIDFILE", str(pidfile))
    # сам _pid_alive проверяется отдельно: здесь важно, что is_running
    # идёт по pidfile, а не через pgrep
    monkeypatch.setattr(engine, "_pid_alive", lambda pid: pid == os.getpid())
    monkeypatch.setattr(
        engine.subprocess, "run",
        lambda *a, **k: pytest.fail("при живом pid pgrep не нужен"),
    )
    assert engine.is_running() is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-специфичный путь")
def test_winws_log_path_in_temp():
    path = engine.winws_log_path()
    assert path.endswith("zapret-warp-winws.log")
    assert os.path.isabs(path)


def test_no_dead_sudo_helper():
    """`_sudo` был мёртвым кодом — не должен вернуться незамеченным."""
    assert not hasattr(engine, "_sudo")
