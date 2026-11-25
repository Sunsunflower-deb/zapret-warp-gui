"""Тесты логирования в файл и Job Object (kill-on-close)."""
import logging
import os
import subprocess
import sys

import pytest

from core import logs, winjob


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logs, "log_dir", lambda: str(tmp_path))
    logs.reset()
    yield tmp_path
    logs.reset()


def test_setup_writes_file(log_dir):
    logger = logs.setup(console=False)
    logger.info("привет")
    for handler in logger.handlers:
        handler.flush()
    assert (log_dir / "zapret-warp.log").exists()
    assert "привет" in (log_dir / "zapret-warp.log").read_text(encoding="utf-8")


def test_setup_is_idempotent(log_dir):
    first = logs.setup(console=False)
    handlers = len(first.handlers)
    second = logs.setup(console=False)
    assert first is second
    assert len(second.handlers) == handlers


def test_child_logger_names(log_dir):
    logs.setup(console=False)
    child = logs.get("engine")
    assert child.name == "zapret-warp.engine"
    logs.get("engine").info("строка")
    assert "zapret-warp.engine" in (log_dir / "zapret-warp.log").read_text(encoding="utf-8")


def test_log_path_points_to_file(log_dir):
    assert logs.log_path() == os.path.join(str(log_dir), "zapret-warp.log")


def test_default_log_dir_has_app_name(monkeypatch):
    for var in ("LOCALAPPDATA", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(os, "name", "nt")
    assert logs.log_dir().endswith("zapret-warp")


def test_rotation_configured(log_dir):
    logger = logs.setup(console=False)
    file_handlers = [h for h in logger.handlers
                     if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert file_handlers
    assert file_handlers[0].maxBytes == logs.MAX_BYTES
    assert file_handlers[0].backupCount == logs.BACKUPS


def test_unwritable_dir_does_not_break(monkeypatch):
    logs.reset()

    def boom():
        raise OSError("нет прав")

    monkeypatch.setattr(logs, "log_dir", boom)
    logger = logs.setup(console=False)
    logger.info("всё равно работает")
    logs.reset()


# --- Job Object -----------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="Job Object — только Windows")
def test_job_object_kills_child_on_release():
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        if not winjob.attach(proc.pid):
            pytest.skip("ОС не разрешила AssignProcessToJobObject (вложенные джобы)")
        assert winjob.active() is True
        assert proc.poll() is None
        winjob.release()
        proc.wait(timeout=10)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        winjob.release()


@pytest.mark.skipif(os.name != "nt", reason="Job Object — только Windows")
def test_attach_unknown_pid_returns_false():
    assert winjob.attach(2 ** 22 + 777) is False


def test_release_without_job_is_safe():
    winjob.release()
    assert winjob.release() is False
