"""Парсер .bat-стратегий zapret → аргументы nfqws/winws."""
import os
import re
import shlex

from . import paths

GAME_FILTER_PORTS = "1024-65535"
GAME_FILTER_OFF = "12"


def list_strategies():
    if not os.path.isdir(paths.STRATEGIES_DIR):
        return []
    return sorted(
        f for f in os.listdir(paths.STRATEGIES_DIR) if f.lower().endswith(".bat")
    )


def _join_continuations(text):
    """Склеивает строки, оканчивающиеся на '^' (cmd line continuation)."""
    out = []
    buf = ""
    for line in text.split("\n"):
        line = line.rstrip()
        if line.endswith("^"):
            buf += line[:-1] + " "
        else:
            out.append(buf + line)
            buf = ""
    if buf:
        out.append(buf)
    return "\n".join(out)


def _substitute(cmd, gamefilter_tcp, gamefilter_udp):
    # ОТНОСИТЕЛЬНЫЕ пути bin/ lists/: nfqws понижает привилегии до nobody и
    # читает файлы из своего cwd (который держит открытым). Абсолютные пути
    # вида /home/<user>/... недоступны nobody (домашний каталог обычно 700).
    cmd = cmd.replace("%BIN%", "bin/")
    cmd = cmd.replace("%LISTS%", "lists/")

    if gamefilter_tcp or gamefilter_udp:
        cmd = cmd.replace("%GameFilter%", GAME_FILTER_PORTS)
        cmd = cmd.replace(
            "%GameFilterTCP%", GAME_FILTER_PORTS if gamefilter_tcp else GAME_FILTER_OFF
        )
        cmd = cmd.replace(
            "%GameFilterUDP%", GAME_FILTER_PORTS if gamefilter_udp else GAME_FILTER_OFF
        )
    else:
        for v in ("GameFilter", "GameFilterTCP", "GameFilterUDP"):
            cmd = cmd.replace(",%" + v + "%", "").replace("%" + v + "%,", "")
            cmd = cmd.replace("%" + v + "%", GAME_FILTER_OFF)

    return cmd


def parse(strategy_name, gamefilter_tcp=False, gamefilter_udp=False):
    path = os.path.join(paths.STRATEGIES_DIR, strategy_name)
    if not os.path.isfile(path):
        raise FileNotFoundError("Стратегия не найдена: " + strategy_name)

    text = open(path, encoding="utf-8", errors="replace").read().replace("\r", "")
    text = _join_continuations(text)

    m = re.search(r'winws\.exe["\s]*(.*)', text)
    if not m:
        raise ValueError("В стратегии не найдена команда winws.exe")

    cmd = _substitute(m.group(1), gamefilter_tcp, gamefilter_udp)
    # Всегда posix=True: posix=False (Windows) НЕ снимает кавычки, и winws
    # получает аргументы вида --hostlist="lists/..." целиком одним «именем» →
    # file_open_test: cannot access hostlist file. После подстановок %BIN%/%LISTS%
    # бэкслешей в cmd нет, поэтому posix=True безопасен и на Windows.
    args = shlex.split(cmd, posix=True)

    wf_tcp = None
    wf_udp = None
    filter_args = []
    for a in args:
        if a.startswith("--wf-tcp="):
            wf_tcp = a[len("--wf-tcp="):]
        elif a.startswith("--wf-udp="):
            wf_udp = a[len("--wf-udp="):]
        else:
            filter_args.append(a)

    return {
        "wf_tcp": wf_tcp,
        "wf_udp": wf_udp,
        "all_args": args,
        "filter_args": filter_args,
    }
