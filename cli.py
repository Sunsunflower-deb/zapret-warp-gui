#!/usr/bin/env python3
"""CLI-режим zapret-warp (без GUI)."""
import argparse
import sys
import time

from core import config, doctor, engine, strategy, warp, wgcf
from core.version import __version__


def _prepare_console():
    """Не падать на консоли с узкой кодировкой.

    На русской Windows stdout — cp1251/cp866, и печать «✅» или «→» валится
    с UnicodeEncodeError: `cli.py doctor` просто не работал. Меняем ошибки
    кодирования на замену — символ покажется как «?», но команда выполнится.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _prepare_console()
    ap = argparse.ArgumentParser(
        prog="zapret-warp",
        description="zapret-warp: Simple Fake + Cloudflare WARP",
    )
    ap.add_argument(
        "command",
        choices=["start", "stop", "status", "strategies", "setup", "doctor", "key"],
    )
    ap.add_argument("--version", action="version",
                    version="zapret-warp " + __version__)
    ap.add_argument("--license-key", default="",
                    help="для 'key': привязать аккаунт к существующему license key")
    ap.add_argument("--force", action="store_true",
                    help="для 'key': перерегистрировать новый аккаунт")
    ap.add_argument("--fooling", default=None,
                    help="переопределить config.json -> fooling (auto|md5sig|badseq|ts)")
    args = ap.parse_args(argv)

    cfg = config.load()
    if args.fooling:
        cfg["fooling"] = args.fooling
    fooling = strategy.resolve_fooling(cfg.get("fooling"))

    if args.command == "strategies":
        print("\n".join(strategy.list_strategies()))
    elif args.command == "status":
        print("DPI-десинк:", "запущен" if engine.is_running() else "остановлен")
        print("Стратегия:", cfg["strategy"], "| fooling:", fooling)
        if warp.installed():
            print("WARP:")
            print("  " + warp.status(cfg).replace("\n", "\n  "))
        else:
            print("WARP: не установлен")
    elif args.command == "doctor":
        print(doctor.format_report(doctor.run()))
    elif args.command == "start":
        p = engine.start(cfg["strategy"], cfg["interface"],
                         cfg["gamefilter_tcp"], cfg["gamefilter_udp"],
                         fooling=cfg.get("fooling"))
        print("DPI-десинк запущен:", cfg["strategy"], "| fooling:", p["fooling"])
        print("  argv:", " ".join(p["all_args"])[:400])
        time.sleep(3)
        if cfg["warp_enabled"] and warp.installed():
            warp.connect(cfg)
            print("WARP: connect выполнен")
    elif args.command == "stop":
        engine.stop()
        if warp.installed():
            warp.disconnect(cfg)
        print("Остановлено")
    elif args.command == "setup":
        engine.setup_root()
    elif args.command == "key":
        wgcf.run_key(args.license_key, args.force)


if __name__ == "__main__":
    sys.exit(main())
