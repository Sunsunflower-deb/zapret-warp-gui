"""Запуск DPI-десинка: nfqws (Linux, через root-helper) / winws.exe (Windows)."""
import os
import subprocess
import tempfile
import time

from . import paths, strategy

HELPER = os.path.join(paths.APP_DIR, "root-helper.sh")


def is_admin():
    """Запущены ли мы с правами администратора/root."""
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def winws_log_path():
    """Куда winws пишет stdout/stderr (для диагностики на Windows)."""
    return os.path.join(tempfile.gettempdir(), "zapret-warp-winws.log")


def winws_log_tail(n=15):
    """Последние n строк лога winws (пустая строка, если лога нет)."""
    return _tail(winws_log_path(), n)


def _tail(path, n=15):
    try:
        with open(path, "rb") as f:
            lines = f.read().decode("utf-8", "replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def _sudo():
    return [] if os.geteuid() == 0 else ["sudo"]


def _run_root(*args):
    """Запустить root-helper.sh (Linux) с правами root.

    Если GUI запущен из терминала — sudo спросит пароль в нём.
    Для запуска двойным кликом настрой NOPASSWD: `sudo python3 cli.py setup`.
    """
    cmd = [HELPER] + list(args)
    if os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(msg or "ошибка root-helper (" + " ".join(cmd[:3]) + ")")
    return r


def is_running():
    if os.name == "nt":
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe"],
            capture_output=True, text=True,
        )
        return "winws.exe" in r.stdout
    r = subprocess.run(["pgrep", "-f", "nfqws"], capture_output=True, text=True)
    return r.returncode == 0


def start(name, interface, gamefilter_tcp, gamefilter_udp):
    p = strategy.parse(name, gamefilter_tcp, gamefilter_udp)
    if os.name == "nt":
        _start_winws(p["all_args"])
    else:
        _run_root(
            "start",
            p["wf_tcp"] or "",
            p["wf_udp"] or "",
            interface or "any",
            *p["filter_args"],
        )


def _start_winws(all_args):
    """Запустить winws.exe и убедиться, что он реально поднялся.

    Раньше мы стартовали процесс «вслепую» — если winws сразу падал
    (нет прав администратора для драйвера WinDivert), GUI всё равно писал
    «запущен», WARP оставался на 51%. Теперь stdout/stderr winws пишутся
    в лог, и через ~2 с проверяется, что процесс ещё жив.
    """
    subprocess.run(["taskkill", "/IM", "winws.exe", "/F"], capture_output=True)

    log_path = winws_log_path()
    try:
        os.remove(log_path)
    except OSError:
        pass

    logf = open(log_path, "wb")
    try:
        proc = subprocess.Popen(
            [paths.desync_binary()] + all_args,
            cwd=paths.APP_DIR,  # чтобы относительные bin/, lists/ резолвились
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(2.0)
        if proc.poll() is not None:
            tail = _tail(log_path)
            raise RuntimeError(
                "winws.exe завершился с кодом {}.\n{}\n"
                "Подсказка: запустите приложение от имени администратора "
                "(нужен драйвер WinDivert).".format(
                    proc.returncode, tail or "лог пуст — вероятно, не хватает прав."))
    finally:
        logf.close()


def stop():
    if os.name == "nt":
        subprocess.run(["taskkill", "/IM", "winws.exe", "/F"], capture_output=True)
    else:
        _run_root("stop")


def list_interfaces():
    if os.name == "nt":
        return ["any"]
    try:
        return ["any"] + sorted(os.listdir("/sys/class/net"))
    except OSError:
        return ["any"]


def setup_root():
    """Одноразовая настройка NOPASSWD для root-helper (нужен root)."""
    if os.name == "nt":
        raise RuntimeError("setup нужен только на Linux")
    import getpass
    user = os.environ.get("SUDO_USER") or os.environ.get("DOAS_USER") \
        or getpass.getuser()
    rule = f"{user} ALL=(root) NOPASSWD: {HELPER}\n"
    dest = "/etc/sudoers.d/zapret-warp"
    with open(dest, "w", encoding="utf-8") as f:
        f.write(rule)
    # проверка синтаксиса
    r = subprocess.run(["visudo", "-cf", dest], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("sudoers не прошёл проверку: " + (r.stderr or ""))
    print("Правило записано:", dest)
    print("  " + rule.strip())
