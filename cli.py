#!/usr/bin/env python3
"""CLI-режим zapret-warp (без GUI)."""
import argparse
import time

from core import config, doctor, engine, strategy, warp, wgcf


def main():
    ap = argparse.ArgumentParser(description="zapret-warp: Simple Fake + Cloudflare WARP")
    ap.add_argument(
        "command",
        choices=["start", "stop", "status", "strategies", "setup", "doctor", "key"],
    )
    ap.add_argument("--license-key", default="",
                    help="для 'key': привязать аккаунт к существующему license key")
    ap.add_argument("--force", action="store_true",
                    help="для 'key': перерегистрировать новый аккаунт")
    args = ap.parse_args()

    cfg = config.load()

    if args.command == "strategies":
        print("\n".join(strategy.list_strategies()))
    elif args.command == "status":
        print("DPI-десинк:", "запущен" if engine.is_running() else "остановлен")
        if warp.installed():
            print("WARP:")
            print("  " + warp.status(cfg).replace("\n", "\n  "))
        else:
            print("WARP: не установлен")
    elif args.command == "doctor":
        print(doctor.format_report(doctor.run()))
    elif args.command == "start":
        engine.start(cfg["strategy"], cfg["interface"],
                     cfg["gamefilter_tcp"], cfg["gamefilter_udp"])
        print("DPI-десинк запущен:", cfg["strategy"])
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
    main()
