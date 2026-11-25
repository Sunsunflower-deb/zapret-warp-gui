# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: сборка Windows-артефактов zapret-warp.
#
# Сборка на Windows:
#   pip install pyinstaller
#   pyinstaller zapret-warp.spec --noconfirm --clean
#
# Результат:
#   dist\zapret-warp.exe      — GUI (без окна консоли, просит права администратора)
#   dist\zapret-warp-cli.exe  — CLI (check/status/doctor/tune/start/stop)
#
# Оба .exe самодостаточны: внутри bin/lists/strategies. Если рядом с .exe
# положить папки bin/ lists/ strategies/ — будут использоваться они
# (списки/стратегии можно править без пересборки).
#
# ПОЧЕМУ ДВА Analysis, А НЕ ОДИН. Если положить оба скрипта в один
# Analysis([...]) и передать a.scripts в каждый EXE, PyInstaller кладёт в
# каждый архив ОБА скрипта, а точкой входа берёт первый — то есть
# zapret-warp-cli.exe запускал GUI и молча висел без окна. Проверено сборкой:
# `zapret-warp-cli.exe --version` не отвечал. Поэтому у каждого .exe свой
# Analysis и своя точка входа.

import glob
import os

# --- файлы Windows-бинарей (nfqws — Linux, не включаем) ---
WIN_BIN = ["winws.exe", "WinDivert.dll", "WinDivert64.sys", "cygwin1.dll"]
WIN_BIN += [os.path.basename(p) for p in glob.glob(os.path.join("bin", "*.bin"))]

datas = [(os.path.join("bin", f), "bin") for f in WIN_BIN]
datas += [("lists", "lists"), ("strategies", "strategies")]


def build(entry, name, *, console, uac_admin):
    """Собрать один onefile-EXE из своей точки входа."""
    analysis = Analysis(
        [entry],
        pathex=[],
        binaries=[],
        datas=datas,
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )
    pyz = PYZ(analysis.pure)
    return EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,           # не сжимаем — winws.exe/WinDivert могут ломаться
        upx_exclude=[],
        runtime_tmpdir=None,
        console=console,
        uac_admin=uac_admin,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


# GUI: прав требует сам — иначе не загрузится драйвер WinDivert.
gui = build("main.py", "zapret-warp", console=False, uac_admin=True)

# CLI: намеренно БЕЗ uac_admin — status/check/doctor должны работать без
# запроса прав. Для start/tune запускайте из терминала от администратора:
# приложение само скажет, если прав не хватает.
cli = build("cli.py", "zapret-warp-cli", console=True, uac_admin=False)
