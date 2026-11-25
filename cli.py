#!/usr/bin/env python3
"""CLI-режим zapret-warp (без GUI)."""
import argparse
import sys
import time

from core import config, doctor, engine, logs, state, strategy, warp, wgcf
from core.version import __version__

COMMANDS = ["start", "stop", "status", "check", "strategies", "setup", "doctor", "key"]


def _prepare_console():
    """Не падать на консоли с узкой кодировкой.

    На русской Windows stdout — cp1251/cp866, и печать «✅» или «→» валится
    с UnicodeEncodeError: `cli.py doctor` просто не работал. Две меры:

    * ошибки кодирования → замена (символ покажется как «?»);
    * при перенаправлении вывода в файл — UTF-8, чтобы `cli.py check > log.txt`
      давал читаемый файл, а не cp866.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if getattr(stream, "isatty", lambda: False)():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _prepare_logging(verbose=False):
    """Лог в файл; в консоль — только по -v (иначе шум в выводе команд)."""
    logs.setup(console=verbose)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="zapret-warp",
        description="zapret-warp: Simple Fake + Cloudflare WARP",
    )
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--version", action="version",
                    version="zapret-warp " + __version__)
    ap.add_argument("--license-key", default="",
                    help="для 'key': привязать аккаунт к существующему license key")
    ap.add_argument("--force", action="store_true",
                    help="для 'key': перерегистрировать новый аккаунт")
    ap.add_argument("--fooling", default=None,
                    help="переопределить config.json -> fooling (auto|md5sig|badseq|ts)")
    ap.add_argument("--timeout", type=float, default=5.0,
                    help="таймаут одной сетевой пробы, с (для 'check')")
    ap.add_argument("--no-probe", action="store_true",
                    help="для 'check': только процессы и статус, без сети")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="дублировать лог в stderr")
    return ap


def main(argv=None):
    _prepare_console()
    args = build_parser().parse_args(argv)
    _prepare_logging(args.verbose)

    cfg = config.load()
    if args.fooling:
        cfg["fooling"] = args.fooling
    fooling = strategy.resolve_fooling(cfg.get("fooling"))
    log = logs.get("cli")
    log.info("команда=%s версия=%s fooling=%s", args.command, __version__, fooling)

    if args.command == "strategies":
        print("\n".join(strategy.list_strategies()))
    elif args.command == "status":
        snapshot = state.collect(cfg, do_probe=False)
        print("\n".join(snapshot.summary_lines()))
    elif args.command == "check":
        snapshot = state.collect(cfg, do_probe=not args.no_probe, timeout=args.timeout)
        print("\n".join(snapshot.summary_lines()))
        print()
        print("Итог:", "работает" if snapshot.healthy else "есть проблемы")
        return 0 if snapshot.healthy else 1
    elif args.command == "doctor":
        print(doctor.format_report(doctor.run()))
    elif args.command == "start":
        parsed = engine.start(cfg["strategy"], cfg["interface"],
                              cfg["gamefilter_tcp"], cfg["gamefilter_udp"],
                              fooling=cfg.get("fooling"))
        print("DPI-десинк запущен:", cfg["strategy"], "| fooling:", parsed["fooling"])
        print("  argv:", " ".join(parsed["all_args"])[:400])
        time.sleep(3)
        if cfg["warp_enabled"] and warp.installed():
            print("WARP:", warp.connect(cfg))
    elif args.command == "stop":
        engine.stop()
        if warp.installed():
            warp.disconnect(cfg)
        print("Остановлено")
    elif args.command == "setup":
        engine.setup_root()
    elif args.command == "key":
        wgcf.run_key(args.license_key, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
