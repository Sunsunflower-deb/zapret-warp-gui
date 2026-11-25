# zapret-warp-gui

Cross-platform (Linux + Windows) GUI/CLI for **DPI desync (zapret) + Cloudflare WARP**.
The desync makes the WARP handshake survive networks that block or throttle
`*.cloudflareclient.com`; WARP then tunnels the rest.

> Russian version: [README.ru.md](README.ru.md)

**Current version: 1.3.0** — see [CHANGELOG.md](CHANGELOG.md).

## Why the order matters

DPI desync first, WARP second. Without desync the TLS handshake to the WARP endpoint
does not complete on a filtered network, so `warp-cli` stays on `Connecting`. The app
does this order for you (`engine.start()` → `warp.connect()`).

## Quick start

```bash
python cli.py doctor      # readiness check, prints the exact fix for each problem
python cli.py start       # desync (sudo on Linux) + WARP
python cli.py status
python cli.py stop
python main.py            # GUI
```

`--version` prints the version:

```bash
python cli.py --version
```

## Requirements

**Linux**

```bash
sudo pacman -S tk nftables            # Arch
sudo apt install python3-tk nftables  # Debian/Ubuntu
```

* Cloudflare WARP (`warp-cli`) is required — `doctor` prints the install command for
  your distro.
* The GUI must run as your **normal user** (a root window cannot reach the display on
  Wayland), privileges for `nft`/`nfqws` go through `root-helper.sh`:
  * from a terminal `sudo` asks for the password there;
  * from a double-click, run once `sudo python3 cli.py setup`
    (NOPASSWD for `root-helper.sh` only).

**Windows**

* Python 3.9+ (tkinter ships with the official installer).
* Cloudflare WARP installed (`warp-cli.exe`).
* Run **as administrator**: `winws.exe` needs the WinDivert driver, `warp-cli` needs
  elevation.

## CLI

| Command | What it does |
|---|---|
| `doctor` | env check (binaries, lists, privileges, `warp-cli`, fooling) + fixes |
| `status` | desync state with PID, active strategy + fooling, WARP state |
| `check` | full snapshot: desync, tunnel, reachability of 6 targets, exit IP; exit code 0/1 |
| `tune` | try ~16 candidate strategies and pick one that works on this network |
| `start` | desync → WARP; prints the effective `argv` |
| `stop` | stop WARP, stop desync, clear firewall table |
| `strategies` | list available `.bat` strategies |
| `setup` | (Linux) install the NOPASSWD rule for `root-helper.sh` |
| `key` | register a WARP account via `wgcf` (needs desync running) |
| `--version` | print the version |
| `--fooling <v>` | override `config.json → fooling` for this run |
| `--timeout <s>` | per-probe timeout for `check` (default 5) |
| `--no-probe` | `check` without network probes |
| `-v` | duplicate the log to stderr |

`check` is the honest answer to “does it work?”:

```text
DPI-десинк: остановлен
Стратегия:  warp_simple_fake.bat | fooling: md5sig
WARP:       Disconnected (Disconnected)
Выходной IP: 203.0.113.10  (colo FRA | warp=off)
Доступность:
  Cloudflare WARP: [OK] ok 214 мс
  YouTube: [OK] ok 209 мс
  Telegram: [OK] ok 321 мс
  Discord: [OK] ok 1175 мс
  Google 204: [OK] ok 624 мс
  DNS: [OK] ok 2 мс

Итог: есть проблемы
```

Each probe returns an error **class**, not just pass/fail: `timeout` (blocked),
`reset`/`tls_*` (the fake reached the server — wrong `fooling`), `refused`, `dns`.
`reset`/`tls_*` on the WARP endpoint is the signature of the bug fixed in 1.1.

Logs are written to `%LOCALAPPDATA%\zapret-warp\zapret-warp.log` (Linux:
`~/.local/state/zapret-warp/`), rotated at 1 MB × 3.

### Autotuning

The repo ships 24 `.bat` strategies and no way to know which one works on your
network. `tune` tries them systematically:

```bash
python cli.py tune --dry-run    # list candidates (16), no side effects
python cli.py tune              # run; needs administrator/root (restarts winws)
python cli.py tune --apply      # save the winner as strategies/tuned.bat
```

Candidates are scored by success rate, median RTT and **leaks**: a `reset`/`tls_*`
answer means the fake reached the server, so a leaky candidate ranks below a clean
one even if it is faster. Default budget is 180 s (`--budget`), attempts per target
is 2 (`--attempts`). Candidates cover `fake`, `fake+multisplit`, `hostfakesplit`,
`multidisorder`, `fakedsplit` × `md5sig`/`md5sig,badseq`/`badseq`.

## Configuration (`config.json`, created on first run)

| Key | Default | Meaning |
|---|---|---|
| `strategy` | `warp_simple_fake.bat` | `.bat` from `strategies/` |
| `interface` | `any` | outbound interface (Linux; `any` = all) |
| `fooling` | `auto` | value of `%Fooling%`: `auto` = `md5sig` on Windows, `ts,md5sig` on Linux. Any zapret fooling list works (`md5sig`, `badseq`, `md5sig,badseq`, `ts`, …) |
| `gamefilter_tcp` / `gamefilter_udp` | `false` | substitute `%GameFilterTCP%`/`%GameFilterUDP%` with game port ranges |
| `kill_engine_on_exit` | `true` | GUI binds `winws.exe` to a Job Object so it dies with the app |
| `warp_enabled` | `true` | connect WARP after desync |
| `warp_mode` | `warp` | `warp`, `warp+doh`, `doh`, `dot`, `warp+dot`, `proxy`, `tunnel_only` |
| `warp_protocol` | `MASQUE` | `MASQUE` or `WireGuard` |
| `warp_masque` | `h2-only` | `h3-with-h2-fallback`, `h3-only`, `h2-only` |
| `warp_endpoint` | `""` | custom endpoint (`warp-cli tunnel endpoint set`), empty = reset |

## Masking: what the strategy actually does and why

The whole point is that the DPI must not read the SNI `*.cloudflareclient.com` from the
WARP handshake. Version 1.1 fixes four things that made the app *easier* to detect than
plain TLS:

| Parameter | Before | Now | Why |
|---|---|---|---|
| `--dpi-desync-fooling` | `ts` hardcoded | `%Fooling%` → `md5sig` on Windows | `ts` requires TCP timestamps, and **Windows has them off by default**. Without a working fooling technique the fake packet reaches the real Cloudflare server and breaks the handshake (the usual "stuck on Connecting") |
| `--dpi-desync-repeats` | `8` | `2` | 8 byte-identical ClientHellos per connection is a signature, not camouflage (and ~5.5 KB of junk per connection) |
| `--dpi-desync-fake-tls-mod` | not set | `rnd,dupsid` | when a custom fake is supplied, zapret **disables** its default `rnd,rndsni,dupsid` randomisation. `rnd` randomises `random`/`session_id` per request, `dupsid` copies the real session id, so the fake looks like a retransmission |
| `--dpi-desync-cutoff` / `--dpi-desync-autottl` | none | `n4` + autottl | desync only the first packets; TTL is chosen so the fake passes the DPI but never reaches the server (does not depend on timestamps) |

Hostlist scope: `lists/list-warp.txt` contains only hosts that actually belong to the
tunnel (`cloudflareclient.com`, `cloudflare-dns.com`, `one.one.one.one`). A broad
`cloudflare.com` would pull every Cloudflare-fronted site into the desync.

Two more facts worth knowing:

* `lists/ipset-all.txt` is **empty by design** (it used to hold `203.0.113.113/32`, an
  RFC 5737 test address, so every `--ipset=` rule matched nothing). The parser now drops
  rules whose only scope was that dead list — dropping just `--ipset=` would have made
  `--filter-tcp=80,443,8443` desync *all* traffic. Fill the file with real CIDRs and the
  rules come back. See [lists/README.md](lists/README.md).
* Strategies are `.bat` files from upstream zapret. The parser (`core/strategy.py`)
  removes their copy-paste artifacts: an isolated `-` token, `%~dp0bin\` (wrong directory),
  and `call service.bat` lines for a script that does not exist in this repo.

## Project layout

```
main.py / cli.py          GUI (tkinter) and CLI
core/config.py            config.json
core/strategy.py          .bat → argv (quotes, %BIN%, %LISTS%, %Fooling%, GameFilter, dead ipset)
core/engine.py            winws.exe (Windows) / nfqws via root-helper.sh + nft (Linux)
core/probe.py             TLS/HTTP/DNS probes with error classification
core/state.py             AppState + Monitor: single source of truth
core/warp.py              warp-cli: state enum, settings, connect with real errors
core/winjob.py            Job Object: winws dies with the GUI
core/logs.py              file logging with rotation
core/wgcf.py              WARP account registration (optional, `cli.py key`)
core/doctor.py            readiness report (ASCII icons on narrow consoles)
core/paths.py             portable layout: next to the .exe → _MEIPASS
root-helper.sh            privileged nft + nfqws start/stop (Linux)
bin/                      nfqws, winws.exe, WinDivert, cygwin1.dll, *.bin fakes
lists/                    host / ipset lists (see lists/README.md)
strategies/               .bat strategies from upstream zapret
tests/                    pytest suite (runs against the real strategies and lists)
```

* Windows: `winws.exe` with WinDivert; relative `bin/`, `lists/` resolve from the app dir.
* Linux: `root-helper.sh` (sudo) creates the `inet zapretunix` nft table, then starts
  `nfqws --daemon --pidfile=/run/zapret-warp/nfqws.pid`. Ports and interface are
  validated before they reach `nft`; stop kills only our own process (by pidfile),
  not every `nfqws` on the machine.

## Windows: building the .exe

PyInstaller does not cross-compile — build on Windows (or via GitHub Actions).

```bat
pip install pyinstaller
pyinstaller zapret-warp.spec --noconfirm --clean
:: results: dist\zapret-warp.exe, dist\zapret-warp-cli.exe
```

Two executables are produced from one spec:

| File | What it is |
|---|---|
| `zapret-warp.exe` | GUI, requests administrator rights (WinDivert driver) |
| `zapret-warp-cli.exe` | CLI: `check`, `status`, `doctor`, `tune`, `start`, `stop`. Deliberately **without** `uac_admin`, so `status`/`check` work unelevated — run it from an elevated terminal for `start`/`tune` |

`zapret-warp.spec` bundles `winws.exe`, `WinDivert.dll`, `WinDivert64.sys`,
`cygwin1.dll` (winws is a Cygwin build), `*.bin`, `lists/`, `strategies/`. If you put
`bin/ lists/ strategies/` next to the `.exe`, those are used instead (edit lists without
rebuilding).

Anti-virus / SmartScreen may flag the binary: WinDivert is a packet driver and is
commonly mistrusted. Add an exclusion for the app folder if you trust the build.

**Why the CLI has to be a separate .exe:** `tune` and `check` are CLI features, and a
PyInstaller build with a single `main.py` entry point simply does not contain `cli.py`
(verified: `core.tuner` was missing from the GUI archive).

## Tests

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

The suite runs against the **real** `.bat` files and lists in the repo, so it also guards
the data: no case-colliding strategy names (they used to lose a file on Windows), no
leftover `%GameFilter%`, no literal `ts` fooling, no dead `--ipset` rules, and `doctor`
survives a cp1251 console.

## Known limitations

* `nfqws` runs as **root** (it needs NFQUEUE). That is how upstream zapret works; the app
  does not drop privileges. `cli.py setup` refuses to install the NOPASSWD rule if
  `root-helper.sh` is group/world-writable.
* The `wgcf` + `wireproxy` path (WireGuard WARP for networks where UDP 2408 is not
  blocked) is **not implemented** in 1.1 — `bin/` does not ship those binaries. Only the
  official `warp-cli` transport is used.
* WARP is a single domain and a single ASN. If `cloudflareclient.com` is blocked by IP,
  no amount of desync helps.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| WARP stuck on `Connecting` / 51 % | fake packets reached the server (fooling ineffective) | check `fooling` in `doctor`; on Windows use `md5sig` or enable timestamps |
| `winws.exe завершился с кодом …` | not elevated / WinDivert blocked by AV | run as administrator, add a Defender exclusion |
| `file_open_test: cannot access hostlist file` | wrong working directory | start via the app, not by copying the command manually |
| WARP connects, sites do not open | WARP itself is throttled, desync not applied | confirm the strategy hostlist matches the endpoint from `warp-cli settings` |
| `doctor` prints `[OK]`/`[!!]` | console cannot render emoji (cp1251) | expected; output is still valid |
| `nfqws: unknown option --dpi-desync-fake-tls-mod` | older `nfqws` in `bin/` | remove `--dpi-desync-fake-tls-mod` from `strategies/warp_simple_fake.bat`; the bundled binary is UPX-packed, so its capabilities cannot be inspected in advance |
