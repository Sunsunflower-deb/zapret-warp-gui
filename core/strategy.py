"""Парсер .bat-стратегий zapret → аргументы nfqws/winws.

Почему стратегии остаются .bat: это формат апстрима zapret, их можно
редактировать руками. Парсер лишь приводит их к argv.
"""
import os
import re
import shlex

from . import paths

GAME_FILTER_PORTS = "1024-65535"

# Отдельный токен "-" — артефакт копипасты в апстрим-стратегиях.
# winws/nfqws на нём спотыкаются, поэтому вычищаем.
_ARTIFACT_TOKENS = frozenset({"-"})

_IPSET_INCLUDE_RE = re.compile(r'--ipset="([^"]+)"|--ipset=(\S+)')
_IPSET_EXCLUDE_RE = re.compile(r'--ipset-exclude="([^"]+)"|--ipset-exclude=(\S+)')
_HOST_SCOPE_RE = re.compile(r"--hostlist(?:-domains)?=")
_GAMEFILTER_ONLY_RE = re.compile(
    r"--filter-(?:tcp|udp)=\s*%GameFilter(?:TCP|UDP)%(?=\s|$)"
)


def list_strategies():
    """Стратегии в strategies/.

    Скрытые файлы (`.tune-*.bat`) — временные файлы автоподбора, в списке
    для пользователя им делать нечего.
    """
    if not os.path.isdir(paths.STRATEGIES_DIR):
        return []
    return sorted(
        f for f in os.listdir(paths.STRATEGIES_DIR)
        if f.lower().endswith(".bat") and not f.startswith(".")
    )


def default_fooling():
    """Значение %Fooling% по умолчанию, если в конфиге "auto".

    md5sig не зависит от ОС и от таймстампов. `ts` работает только при
    включённых TCP timestamps, а в Windows они выключены по умолчанию:
    без работающего fooling фейковый пакет доходит до реального сервера
    и ломает TLS-рукопожатие (см. docs/README → «fooling»).
    """
    return "md5sig" if os.name == "nt" else "ts,md5sig"


def resolve_fooling(value=None):
    """config["fooling"] → строка для подстановки в argv."""
    v = (value or "").strip()
    if not v or v.lower() == "auto":
        return default_fooling()
    return v


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


def _list_file_path(target):
    """Путь к списку: в argv он относительный (lists/... или bin/...)."""
    if os.path.isabs(target):
        return target
    norm = target.replace("\\", "/")
    base = os.path.basename(norm)
    for cand in (
        os.path.join(paths.APP_DIR, norm),
        os.path.join(paths.LISTS_DIR, base),
        os.path.join(paths.APP_DIR, base),
    ):
        if os.path.isfile(cand):
            return cand
    return os.path.join(paths.APP_DIR, norm)


def has_entries(path):
    """Есть ли в списке хоть одна рабочая строка (не пустая и не комментарий)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    return True
    except OSError:
        return False
    return False


def _apply_gamefilter(cmd, gamefilter_tcp, gamefilter_udp):
    """Подставить или удалить %GameFilterTCP% / %GameFilterUDP%.

    Если правило существует ТОЛЬКО для игровых портов, при выключенном
    чекбоксе его надо удалять целиком: раньше на его месте оставался
    мусорный `--filter-udp=12` — правило на порт, который никогда не несёт TLS.
    """
    out = []
    for prof in cmd.split("--new"):
        only_gamefilter = bool(_GAMEFILTER_ONLY_RE.search(prof))
        if only_gamefilter:
            uses_tcp = "%GameFilterTCP%" in prof or "%GameFilter%" in prof
            uses_udp = "%GameFilterUDP%" in prof or "%GameFilter%" in prof
            keep = (gamefilter_tcp and uses_tcp) or (gamefilter_udp and uses_udp)
            if not keep:
                continue
            if not gamefilter_udp and uses_udp and not gamefilter_tcp:
                continue
            if not gamefilter_tcp and uses_tcp and not gamefilter_udp:
                continue

        if gamefilter_tcp or gamefilter_udp:
            prof = prof.replace("%GameFilter%", GAME_FILTER_PORTS)
        else:
            prof = prof.replace(",%GameFilter%", "").replace("%GameFilter%,", "")
            prof = prof.replace("%GameFilter%", "")

        if gamefilter_tcp:
            prof = prof.replace("%GameFilterTCP%", GAME_FILTER_PORTS)
        else:
            prof = prof.replace(",%GameFilterTCP%", "").replace("%GameFilterTCP%,", "")
            prof = prof.replace("%GameFilterTCP%", "")

        if gamefilter_udp:
            prof = prof.replace("%GameFilterUDP%", GAME_FILTER_PORTS)
        else:
            prof = prof.replace(",%GameFilterUDP%", "").replace("%GameFilterUDP%,", "")
            prof = prof.replace("%GameFilterUDP%", "")

        out.append(prof)
    return "--new".join(out)


def _prune_dead_ipset(cmd):
    """Убрать ссылки на ipset-файлы, в которых нет адресов.

    В репозитории `lists/ipset-all.txt` — заготовка (раньше там лежал
    единственный тестовый адрес 203.0.113.113/32 из RFC 5737), поэтому
    правила вида `--filter-tcp=80,443,8443 --ipset=...` не матчили ничего.
    Важно: просто выкинуть `--ipset=` нельзя — правило осталось бы без
    ограничения по адресам и задурило бы весь трафик на этих портах.
    Поэтому правило без hostlist-скоупа удаляется целиком.
    """
    out = []
    for prof in cmd.split("--new"):
        dead_include = [
            m.group(1) or m.group(2)
            for m in _IPSET_INCLUDE_RE.finditer(prof)
            if not has_entries(_list_file_path(m.group(1) or m.group(2)))
        ]
        if dead_include:
            if not _HOST_SCOPE_RE.search(prof):
                continue
            prof = _IPSET_INCLUDE_RE.sub("", prof)

        # Пустой exclude-лист = «ничего не исключаем»: аргумент бесполезен, но безвреден
        prof = _IPSET_EXCLUDE_RE.sub(
            lambda m: (
                ""
                if not has_entries(_list_file_path(m.group(1) or m.group(2)))
                else m.group(0)
            ),
            prof,
        )
        out.append(prof)
    return "--new".join(out)


def _substitute(cmd, gamefilter_tcp, gamefilter_udp, fooling):
    # ОТНОСИТЕЛЬНЫЕ пути bin/, lists/: nfqws читает файлы из своего cwd,
    # а absolute-пути вида /home/<user>/... могут быть недоступны процессу
    # с понижёнными привилегиями (домашний каталог обычно 700).
    cmd = cmd.replace("%BIN%", "bin/")
    cmd = cmd.replace("%LISTS%", "lists/")
    cmd = cmd.replace("%Fooling%", fooling)
    cmd = _apply_gamefilter(cmd, gamefilter_tcp, gamefilter_udp)
    cmd = _prune_dead_ipset(cmd)
    return cmd


def parse(strategy_name, gamefilter_tcp=False, gamefilter_udp=False,
          fooling=None):
    """Разобрать стратегию из strategies/ в argv."""
    path = os.path.join(paths.STRATEGIES_DIR, strategy_name)
    if not os.path.isfile(path):
        raise FileNotFoundError("Стратегия не найдена: " + strategy_name)
    return parse_file(path, gamefilter_tcp=gamefilter_tcp,
                      gamefilter_udp=gamefilter_udp, fooling=fooling)


def parse_file(path, gamefilter_tcp=False, gamefilter_udp=False, fooling=None):
    """Разобрать конкретный .bat-файл в argv.

    Возвращает dict с ключами wf_tcp / wf_udp / all_args / filter_args / fooling.
    """
    resolved_fooling = resolve_fooling(fooling)
    if not os.path.isfile(path):
        raise FileNotFoundError("Стратегия не найдена: " + path)

    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read().replace("\r", "")
    text = _join_continuations(text)

    m = re.search(r'winws\.exe["\s]*(.*)', text)
    if not m:
        raise ValueError("В стратегии не найдена команда winws.exe")

    cmd = _substitute(m.group(1), gamefilter_tcp, gamefilter_udp,
                      resolved_fooling)
    # Всегда posix=True: posix=False (Windows) НЕ снимает кавычки, и winws
    # получает аргументы вида --hostlist="lists/..." целиком одним «именем» →
    # file_open_test: cannot access hostlist file. После подстановок %BIN%/%LISTS%
    # бэкслешей в cmd нет, поэтому posix=True безопасен и на Windows.
    args = [a for a in shlex.split(cmd, posix=True) if a not in _ARTIFACT_TOKENS]

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
        "fooling": resolved_fooling,
    }
