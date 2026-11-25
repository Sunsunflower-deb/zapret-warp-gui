"""Тесты CLI: версия, устойчивость вывода на cp1251-консоли."""
import os
import subprocess
import sys

import pytest

import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "zapret-warp" in out


def test_prepare_console_is_idempotent():
    cli._prepare_console()
    cli._prepare_console()


def test_strategies_lists_all(capsys):
    cli.main(["strategies"])
    out = capsys.readouterr().out.split()
    assert "warp_simple_fake.bat" in out
    assert len(out) >= 20


@pytest.mark.parametrize("encoding", ["cp1251", "utf-8"])
def test_doctor_survives_narrow_console(encoding):
    """Регресс: на cp1251 `doctor` падал с UnicodeEncodeError."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    r = subprocess.run(
        [sys.executable, "cli.py", "doctor"],
        cwd=ROOT, capture_output=True, env=env, timeout=120,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-2000:]
    assert b"Traceback" not in r.stderr
