# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: сборка zapret-warp.exe (Windows).
#
# Сборка на Windows:
#   pip install pyinstaller
#   pyinstaller zapret-warp.spec --noconfirm --clean
#
# Результат: dist\zapret-warp.exe — единый .exe, внутри bin/lists/strategies.
# Если рядом с .exe положить папки bin/ lists/ strategies/ — будут
# использоваться они (списки/стратегии можно править без пересборки).

import glob
import os

# --- файлы Windows-бинарей (nfqws — Linux, не включаем) ---
WIN_BIN = ["winws.exe", "WinDivert.dll", "WinDivert64.sys", "cygwin1.dll"]
WIN_BIN += [os.path.basename(p) for p in glob.glob(os.path.join("bin", "*.bin"))]

datas = [(os.path.join("bin", f), "bin") for f in WIN_BIN]
datas += [("lists", "lists"), ("strategies", "strategies")]

a = Analysis(
    ["main.py"],
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

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="zapret-warp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # не сжимаем — winws.exe/WinDivert могут ломаться
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # GUI без окна консоли
    # exe сам запросит права администратора (нужны WinDivert и warp-cli)
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
