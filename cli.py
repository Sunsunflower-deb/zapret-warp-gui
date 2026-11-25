#!/usr/bin/env python3
"""CLI-режим zapret-warp (без GUI)."""
import argparse
import os
import sys
import time

from core import config, doctor, engine, logs, state, strategy, tuner, warp, wgcf
from core.version import __version__

COMMANDS = ["start", "stop", "status", "check", "tune", "strategies", "setup",
            "doctor", "key"]


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
    tune = ap.add_argument_group("tune")
    tune.add_argument("--dry-run", action="store_true",
                      help="для 'tune': только показать кандидатов, ничего не запускать")
    tune.add_argument("--attempts", type=int, default=tuner.DEFAULT_ATTEMPTS,
                      help="для 'tune': сколько раз пробовать каждую цель")
    tune.add_argument("--budget", type=float, default=tuner.DEFAULT_BUDGET,
                      help="для 'tune': лимит времени на весь подбор, с")
    tune.add_argument("--apply", action="store_true",
                      help="для 'tune': сохранить победителя в strategies/tuned.bat")
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
    elif args.command == "tune":
        return _cmd_tune(args, cfg)
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


def _cmd_tune(args, cfg):
    """Автоподбор стратегии (этап 6 плана)."""
    candidates = tuner.build_candidates()
    if args.dry_run:
        for candidate in candidates:
            print(candidate.id)
            print("    " + candidate.label)
        print()
        print(f"всего кандидатов: {len(candidates)}")
        return 0

    if os.name == "nt" and not engine.is_admin():
        print("Нужны права администратора: подбор перезапускает winws.exe.")
        print("Откройте терминал от имени администратора и повторите.")
        return 2

    was_running = engine.is_running()
    print(f"Подбор: {len(candidates)} кандидатов, {args.attempts} попыток на цель, "
          f"бюджет {args.budget:.0f} с")
    print("Цели: " + ", ".join(f"{t.name} ({t.target})" for t in tuner.TUNE_TARGETS))
    print()
    try:
        result = tuner.tune(attempts=args.attempts, timeout=args.timeout,
                            budget=args.budget,
                            progress=lambda r: print("  " + r.line(), flush=True))
    except KeyboardInterrupt:
        print()
        print("Прервано пользователем.")
        return 130
    finally:
        if not was_running:
            try:
                engine.stop()
            except Exception as exc:  # noqa: BLE001
                logs.get("cli").warning("не удалось остановить десинк: %s", exc)

    print()
    if result.best is None or not result.best.ok:
        print("Ни один кандидат не заработал — конфиг не изменён.")
        print("Проверьте: права администратора, список list-warp.txt и доступность "
              "endpoint'а WARP (`python cli.py check`).")
        return 1

    best = result.best
    print("Лучший:", best.candidate.label)
    print(f"  score {best.score:.1f} · успех {best.ok_rate * 100:.0f}% · "
          f"медиана {best.median_rtt:.0f} мс")
    if result.stopped_by_budget:
        print("  (бюджет времени исчерпан: проверены не все кандидаты)")
    if args.apply:
        path = tuner.apply(best.candidate, cfg)
        print("Сохранено:", path)
        print("config.json: strategy=tuned.bat, fooling=" + best.candidate.fooling)
    else:
        print("Чтобы сохранить результат, повторите с --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
