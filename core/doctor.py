"""Проверка готовности приложения («doctor»): все ли компоненты на месте."""
import os
import shutil
import sys

from . import engine, paths, warp

OK = "\u2705"
BAD = "\u274c"
WARN = "\u26a0\ufe0f"


def _tk_ok():
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def _nft_ok():
    if os.name == "nt":
        return None  # не нужен на Windows
    return shutil.which("nft") is not None


def _admin_ok():
    if os.name != "nt":
        return True  # root-права проверяются отдельно (root-helper)
    return engine.is_admin()


def run():
    """Возвращает список кортежей (имя, статус: 'ok'/'bad'/'warn', деталь, фикс)."""
    report = []

    def add(name, ok, detail, fix=""):
        report.append((name, "ok" if ok else ("warn" if not fix else "bad"),
                       detail, fix))

    # --- данные приложения ---
    add("bin/ (бинари)", os.path.isdir(paths.BIN_DIR),
        "есть" if os.path.isdir(paths.BIN_DIR) else "нет",
        "папка bin/ отсутствует")
    add("nfqws/winws", os.path.isfile(paths.desync_binary()),
        os.path.basename(paths.desync_binary()),
        "положите nfqws (Linux) или winws.exe (Windows) в bin/")
    add("lists/", os.path.isdir(paths.LISTS_DIR),
        "есть" if os.path.isdir(paths.LISTS_DIR) else "нет",
        "папка lists/ отсутствует")
    add("strategies/", os.path.isdir(paths.STRATEGIES_DIR),
        "есть" if os.path.isdir(paths.STRATEGIES_DIR) else "нет",
        "папка strategies/ отсутствует")

    # --- python / GUI ---
    add("Python", sys.version_info >= (3, 8), sys.version.split()[0],
        "нужен Python 3.8+")
    add("tkinter (GUI)", _tk_ok(),
        "доступен" if _tk_ok() else "НЕ установлен",
        "Linux: sudo pacman -S tk (Arch) / sudo apt install python3-tk (Debian)")

    # --- привилегии / движок ---
    if os.name != "nt":
        nft = _nft_ok()
        add("nftables", bool(nft), nft or "nft не найден",
            "Linux: sudo pacman -S nftables (Arch) / sudo apt install nftables")
        add("root-helper.sh", os.path.isfile(os.path.join(paths.APP_DIR, "root-helper.sh")),
            "есть" if os.path.isfile(os.path.join(paths.APP_DIR, "root-helper.sh")) else "нет",
            "файл root-helper.sh отсутствует")
    else:
        add("Права администратора", _admin_ok(),
            "есть" if _admin_ok() else "НЕТ",
            "ПКМ по zapret-warp.exe → «Запуск от имени администратора» "
            "(нужен для WinDivert и warp-cli)")
        if os.path.isfile(engine.winws_log_path()):
            tail = "… " + engine.winws_log_tail(3).replace("\n", " | ")
            add("winws.log (хвост)", "error" not in tail.lower(), tail,
                "если winws падает — смотри полный лог: "
                + engine.winws_log_path())

    # --- WARP ---
    cli = warp.find_cli()
    add("warp-cli (WARP)", bool(cli), cli or "не найден", warp.install_guide())
    if cli:
        reg = warp.registration({})
        reg_first = (reg.splitlines() or ["нет ответа"])[0][:80]
        add("warp-cli регистрация", bool(reg.strip()), reg_first,
            "откройте Cloudflare WARP/1.1.1.1 и войдите в аккаунт (free)")

    return report


def format_report(report):
    lines = ["=== Проверка готовности zapret-warp ===", ""]
    for name, status, detail, fix in report:
        icon = {"ok": OK, "bad": BAD, "warn": WARN}[status]
        lines.append(f"{icon} {name}: {detail}")
    lines.append("")
    need_fix = [r for r in report if r[1] == "bad"]
    if need_fix:
        lines.append("Что нужно исправить:")
        for name, status, detail, fix in need_fix:
            lines.append(f"  - {name}: {fix}")
    else:
        lines.append("Все компоненты на месте. Можно запускать start.")
    return "\n".join(lines)
