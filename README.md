# zapret-warp-gui

Cross-platform (Linux + Windows) app: **DPI desync (Simple Fake) + Cloudflare WARP** with a GUI — all in one compact package.

- **DPI desync**: `nfqws` (Linux) / `winws.exe` (Windows) — `general_SIMPLE_FAKE.bat` strategy.
- **VPN**: Cloudflare WARP (`warp-cli` / `warp-cli.exe`), "HTTPS + UDP" mode (MASQUE: HTTP/3 + HTTP/2 fallback).

> Русская версия: [README.ru.md](README.ru.md)

## Layout

```
zapret-warp-gui/
├── main.py              # GUI (tkinter)
├── cli.py               # CLI: start/stop/status/doctor/setup/key/strategies
├── root-helper.sh       # privileged nfqws/nft operations (Linux)
├── core/                # backend (config, strategy, engine, warp, doctor, wgcf)
├── bin/                 # nfqws (Linux), winws.exe+WinDivert+*.bin (Windows),
│                        # wgcf + wireproxy (embedded WARP for unrestricted networks)
├── lists/               # host / ipset lists
├── strategies/          # .bat strategies
├── wgcf/                # embedded WARP account (wgcf-account + profile) — private, gitignored
├── zapret-warp.spec     # PyInstaller spec for the Windows .exe
├── build_windows.bat    # build the .exe on Windows
└── config.json          # created on first run
```

## Quick start (out of the box)

```bash
# 1. Check that everything is present (Python, binaries, lists, warp-cli, tkinter)
python3 cli.py doctor

# 2. If something is missing — doctor prints the exact command to install it
#    (e.g. Cloudflare WARP's warp-cli or tkinter).

# 3. Run
python3 cli.py start        # nfqws (asks for sudo) + WARP
# or the GUI:
python3 main.py             # the "Check" button = same doctor
```

`doctor` reports ✅/❌ for every component plus the **exact fix command** for your
distro (Arch/Debian/Fedora/Windows).

## Requirements

**Linux**
```bash
sudo pacman -S tk nftables          # Arch
# or: sudo apt install python3-tk nftables   # Debian/Ubuntu
```
- **Cloudflare WARP** (`warp-cli`) is required: `doctor` tells you how to install it
  (Arch: `yay -S cloudflare-warp-bin`; Debian/Ubuntu: Cloudflare's official repo).
  The app auto-detects warp-cli (in PATH and in standard install paths).
- The GUI must run as your **normal user** (NOT via sudo — on Wayland/Hyprland a
  root window can't reach the display). Privileges for nfqws/nft go through
  `root-helper.sh`:
  - launched from a terminal: sudo asks for the password there;
  - launched by double-click: run once `sudo python3 cli.py setup`
    (NOPASSWD rule for root-helper.sh only).

**Windows**
- Python 3.9+ (tkinter is bundled with the official installer).
- Cloudflare WARP (warp-cli.exe): install the official Cloudflare WARP app.
- Run **as administrator** (WinDivert driver needed by winws.exe).

## Usage

**CLI**
```bash
python3 cli.py doctor       # readiness check + install hints
python3 cli.py status       # nfqws + WARP status
python3 cli.py start        # nfqws → WARP (order is automatic)
python3 cli.py stop
python3 cli.py setup        # (Linux) NOPASSWD for root-helper: sudo python3 cli.py setup
python3 cli.py key          # obtain a WARP key (wgcf) — obfuscation is built in:
                            #   auto-starts nfqws → wgcf register → wgcf generate
python3 cli.py key --license-key <KEY>   # bind this device to an existing account
python3 cli.py key --force               # register a brand-new account
python3 cli.py strategies
```

**Obtaining a WARP key on any device.** Registration uses HTTPS to
`api.cloudflareclient.com`, and nfqws (Simple Fake) obfuscates `cloudflareclient.com` —
so `cli.py key` works **natively, with no pre-existing tunnel**. Every device needs
its own registration, but you can bind them all to one account using the
`license_key` from `wgcf/wgcf-account.toml`. Keys are stored in `wgcf/`
(gitignored — they are private).

**GUI** — `python3 main.py` (Linux) / `python main.py` (Windows).

## Order matters

**nfqws/winws first, then WARP.** The Simple Fake strategy obfuscates the WARP
handshake to `*.cloudflareclient.com` (domain present in `lists/list-general.txt`),
so WARP cannot connect without the desync running. The app handles this automatically.

## Windows: building the .exe

PyInstaller does not cross-compile — **the .exe must be built on Windows**
(or via GitHub Actions, see below).

**Locally on Windows:**
```bat
:: copy the project folder to Windows, then in cmd:
pip install pyinstaller
pyinstaller zapret-warp.spec --noconfirm --clean
:: result: dist\zapret-warp.exe
```
Or simply double-click **`build_windows.bat`** (it installs PyInstaller and builds).

`zapret-warp.spec` bundles everything into the .exe: `winws.exe`, `WinDivert.dll`,
`WinDivert64.sys`, `cygwin1.dll` (required — winws is a Cygwin build), `*.bin`,
`lists/`, `strategies/`. If you place `bin/ lists/ strategies/` folders next to the
.exe, they are used instead (editable lists/strategies without rebuilding).

**Or via GitHub Actions** (no local Windows needed): push the repo to GitHub →
Actions tab → **build-exe** workflow → Run → download the `zapret-warp-windows` artifact.

## How it works

- Strategies are `.bat` files with `winws.exe` commands. The `core/strategy.py`
  parser extracts the arguments and substitutes **relative** `bin/`, `lists/`
  paths (important: nfqws drops privileges to nobody and reads files from its cwd).
- Linux: `root-helper.sh` (sudo) → nftables rules + `nfqws --daemon`.
- Windows: `winws.exe` directly (WinDivert intercepts traffic, no firewall setup).
- `wgcf/` + `bin/wgcf` + `bin/wireproxy` — embedded WARP (WireGuard) for networks
  where UDP 2408 is not blocked by the ISP. On restrictive networks (like the
  author's) only the official MASQUE client works, so the app manages the system
  warp-cli by default.
