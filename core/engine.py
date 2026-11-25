"""Запуск DPI-десинка: nfqws (Linux, через root-helper) / winws.exe (Windows)."""
import csv
import os
import subprocess
import tempfile
import time

from . import paths, strategy, winjob
from .logs import get as _log_get

HELPER = os.path.join(paths.APP_DIR, "root-helper.sh")

# nfqws пишет сюда PID (--pidfile). Файл нужен, чтобы останавливать именно
# свой процесс, а не любой `nfqws` в системе (раньше был `pkill -f nfqws`).
PIDFILE = "/run/zapret-warp/nfqws.pid"


def _nowin():
    """Windows: не порождать окно консоли у tasklist/taskkill (из windowed-GUI
    иначе каждые 3 с мигает окно терминала)."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def is_admin():
    """Запущены ли мы с правами администратора/root."""
    if os.name != "nt":
        return os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ensure_tcp_timestamps():
    """Включить TCP timestamps (Windows) для работы `--dpi-desync-fooling=ts`.

    `ts` подделывает TSval, и сервер отбрасывает фейк. TCP timestamps
    генерирует ОС, а в Windows они выключены по умолчанию — тогда fooling
    не работает, и 8 копий чужого ClientHello уходят в реальный сервер.
    Команда идемпотентна, но требует прав администратора.
    Возвращает True, если настройка применилась (на Linux — всегда True).
    """
    if os.name != "nt":
        return True
    try:
        r = subprocess.run(
            ["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"],
            capture_output=True, text=True, **_nowin(),
        )
    except OSError:
        return False
    return r.returncode == 0


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


def nfqws_pid():
    """PID работающего nfqws из pidfile (None, если файла нет/битый)."""
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            return int(f.read().strip()) or None
    except (OSError, ValueError):
        return None


def _pid_alive(pid):
    """Жив ли процесс с таким PID.

    Только POSIX. На Windows `os.kill(pid, 0)` не «проверяет» процесс, а
    убивает его (`TerminateProcess`), поэтому туда не идём: проверка
    десинка на Windows делается через tasklist в is_running().
    """
    if os.name == "nt":
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def desync_pid():
    """PID процесса десинка (None, если не запущен).

    Нужен состоянию приложения и диагностике: «процесс жив» без PID —
    бесполезное утверждение, если в системе два winws.
    """
    if os.name == "nt":
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, **_nowin(),
        )
        for row in csv.reader((r.stdout or "").splitlines()):
            if row and row[0].lower().endswith("winws.exe"):
                try:
                    return int(row[1])
                except (IndexError, ValueError):
                    return None
        return None
    return nfqws_pid()


def is_running():
    if os.name == "nt":
        return desync_pid() is not None

    pid = nfqws_pid()
    if pid:
        return _pid_alive(pid)
    # Фолбэк для установок, запущенных до появления pidfile
    r = subprocess.run(
        ["pgrep", "-f", "bin/nfqws|/nfqws "], capture_output=True, text=True
    )
    return r.returncode == 0


def start(name, interface, gamefilter_tcp, gamefilter_udp, fooling=None,
          kill_with_parent=False):
    """Поднять десинк по имени стратегии из strategies/.

    kill_with_parent — только для GUI: привязать winws к Job Object, чтобы он
    гарантированно умирал вместе с приложением. CLI этого делать не должен:
    он завершается сразу после запуска, и туннель умер бы вместе с ним.
    """
    p = strategy.parse(name, gamefilter_tcp, gamefilter_udp, fooling=fooling)
    return start_parsed(p, interface=interface, kill_with_parent=kill_with_parent)


def start_parsed(p, interface="any", kill_with_parent=False):
    """Запустить десинк по уже разобранной стратегии (dict из strategy.parse).

    Отдельная точка входа нужна автоподбору: он генерирует стратегию
    во временный .bat и запускает её тем же путём, что и штатные, — иначе
    подбор проверял бы не то, что потом реально работает.
    """
    log = _log_get("engine")
    log.info("старт: fooling=%s argv=%s", p.get("fooling"), " ".join(p["all_args"]))
    if os.name == "nt":
        if "ts" in (p.get("fooling") or "") and not ensure_tcp_timestamps():
            log.warning("не удалось включить TCP timestamps: fooling=ts может не работать")
        _start_winws(p["all_args"], kill_with_parent=kill_with_parent)
    else:
        _run_root(
            "start",
            p["wf_tcp"] or "",
            p["wf_udp"] or "",
            interface or "any",
            *p["filter_args"],
        )
    log.info("десинк запущен (pid %s)", desync_pid())
    return p


def _start_winws(all_args, kill_with_parent=False):
    """Запустить winws.exe и убедиться, что он реально поднялся.

    Раньше мы стартовали процесс «вслепую» — если winws сразу падал
    (нет прав администратора для драйвера WinDivert), GUI всё равно писал
    «запущен», WARP оставался на 51%. Теперь stdout/stderr winws пишутся
    в лог, и через ~2 с проверяется, что процесс ещё жив.
    """
    subprocess.run(["taskkill", "/IM", "winws.exe", "/F"], capture_output=True, **_nowin())

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
        if kill_with_parent and not winjob.attach(proc.pid):
            _log_get("engine").warning(
                "не удалось привязать winws к Job Object — процесс может остаться "
                "после закрытия приложения")
    finally:
        logf.close()


def stop():
    log = _log_get("engine")
    if os.name == "nt":
        subprocess.run(["taskkill", "/IM", "winws.exe", "/F"], capture_output=True, **_nowin())
    else:
        _run_root("stop")
    log.info("десинк остановлен")


def list_interfaces():
    if os.name == "nt":
        return ["any"]
    try:
        return ["any"] + sorted(os.listdir("/sys/class/net"))
    except OSError:
        return ["any"]


def _helper_is_safe():
    """root-helper.sh не должен быть writable для группы/всех.

    Иначе NOPASSWD-правило в sudoers даёт любому процессу этого
    пользователя root: достаточно дописать строку в скрипт.
    """
    try:
        st = os.stat(HELPER)
    except OSError:
        return False
    return not (st.st_mode & 0o022)


def setup_root():
    """Одноразовая настройка NOPASSWD для root-helper (нужен root)."""
    if os.name == "nt":
        raise RuntimeError("setup нужен только на Linux")
    if not _helper_is_safe():
        raise RuntimeError(
            "root-helper.sh доступен на запись группе/остальным — это дыра "
            "в root: исправьте права (chmod go-w) и повторите.\n  " + HELPER
        )
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
