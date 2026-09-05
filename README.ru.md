# zapret-warp-gui

Кросс-платформенное приложение (Linux + Windows): **DPI-десинк (Simple Fake) + Cloudflare WARP** с GUI — всё в одном компактном пакете.

- **DPI-десинк**: `nfqws` (Linux) / `winws.exe` (Windows) — стратегия `general_SIMPLE_FAKE.bat`.
- **VPN**: Cloudflare WARP (`warp-cli` / `warp-cli.exe`), режим «HTTPS + UDP» (MASQUE: HTTP/3 + фолбэк HTTP/2).

## Структура

```
zapret-warp-gui/
├── main.py              # GUI (tkinter)
├── cli.py               # CLI: start/stop/status/doctor/setup/strategies
├── root-helper.sh       # привилегированные операции nfqws/nft (Linux)
├── core/                # бэкенд (config, strategy, engine, warp, doctor)
├── bin/                 # nfqws (Linux), winws.exe+WinDivert+*.bin (Windows),
│                        # wgcf + wireproxy (встроенный WARP для сетей без блокировки)
├── lists/               # списки хостов/ipset
├── strategies/          # .bat-стратегии
├── wgcf/                # аккаунт встроенного WARP (wgcf-account + profile)
├── zapret-warp.spec     # PyInstaller-сборка Windows .exe
├── build_windows.bat    # сборка .exe на Windows
└── config.json          # создаётся при первом запуске
```

## Быстрый старт («из коробки»)

```bash
# 1. Проверка: всё ли на месте (Python, бинари, списки, warp-cli, tkinter)
python3 cli.py doctor

# 2. Если чего-то нет — doctor подскажет, что доустановить.
#    Например, warp-cli (Cloudflare WARP) и tkinter.

# 3. Запуск
python3 cli.py start        # nfqws (спросит sudo) + WARP
# или GUI:
python3 main.py             # кнопка «Проверка» = тот же doctor
```

`doctor` показывает по каждому компоненту ✅/❌ и **точную команду**, как его
доустановить на твоём дистрибутиве (Arch/Debian/Fedora/Windows).

## Требования

**Linux**
```bash
sudo pacman -S tk nftables        # Arch
# или: sudo apt install python3-tk nftables   # Debian/Ubuntu
```
- **Cloudflare WARP** (`warp-cli`) — обязателен: `doctor` покажет как поставить
  (Arch: `yay -S cloudflare-warp-bin`; Debian/Ubuntu: официальный репозиторий
  Cloudflare). Приложение само находит warp-cli (в PATH и стандартных путях).
- GUI запускается **от обычного пользователя** (НЕ через sudo — на
  Wayland/Hyprland root-окно не подключится к дисплею). Привилегии для nfqws/nft
  берутся через `root-helper.sh`:
  - из терминала: sudo спросит пароль;
  - двойным кликом: один раз `sudo python3 cli.py setup`
    (NOPASSWD только для root-helper.sh).

**Windows**
- Python 3.9+ (tkinter идёт в комплекте).
- Cloudflare WARP (warp-cli.exe): установи официальное приложение Cloudflare WARP.
- Запуск **от администратора** (нужен WinDivert для winws.exe).

## Использование

**CLI**
```bash
python3 cli.py doctor       # проверка готовности + подсказки по установке
python3 cli.py status       # статус nfqws + WARP
python3 cli.py start        # nfqws → WARP (порядок автоматический)
python3 cli.py stop
python3 cli.py setup        # (Linux) NOPASSWD для root-helper: sudo python3 cli.py setup
python3 cli.py key          # получить WARP-ключ (wgcf) — обфускация встроена:
                            #   сам поднимет nfqws → wgcf register → wgcf generate
python3 cli.py key --license-key <KEY>   # привязать к существующему аккаунту
python3 cli.py key --force               # новый аккаунт
python3 cli.py strategies
```

**Получение WARP-ключа на любом устройстве.** Регистрация идёт по HTTPS к
`api.cloudflareclient.com`, а nfqws (Simple Fake) обфусцирует `cloudflareclient.com` —
поэтому `cli.py key` работает **нативно, без предварительного туннеля**.
На каждом устройстве нужна своя регистрация, но все устройства можно привязать
к одной учётке через license_key из `wgcf/wgcf-account.toml`.
Ключи сохраняются в `wgcf/` (в .gitignore — приватные).

**GUI** — `python3 main.py` (Linux) / `python main.py` (Windows).

## Важно про порядок

**Сначала nfqws/winws, потом WARP.** Стратегия Simple Fake обфусцирует хендшейк
WARP к `*.cloudflareclient.com` (домен в `lists/list-general.txt`) — без десинка
WARP не поднимется. Приложение делает это автоматически.

## Windows: сборка .exe

PyInstaller не умеет кросс-компиляцию — **.exe собирается на Windows**
(или через GitHub Actions, см. ниже).

**Локально на Windows:**
```bat
:: скопировать папку проекта на Windows, затем в cmd:
pip install pyinstaller
pyinstaller zapret-warp.spec --noconfirm --clean
:: результат: dist\zapret-warp.exe
```
Либо просто двойной клик по **`build_windows.bat`** (сам поставит PyInstaller и соберёт).

`zapret-warp.spec` кладёт внутрь .exe всё нужное: `winws.exe`, `WinDivert.dll`,
`WinDivert64.sys`, `cygwin1.dll` (нужна — winws Cygwin-сборка), `*.bin`,
`lists/`, `strategies/`. Если рядом с exe положить папки `bin/ lists/ strategies/`,
будут использоваться они (списки/стратегии можно править без пересборки).

**Или через GitHub Actions** (без локальной Windows): залей репозиторий на GitHub →
вкладка Actions → workflow **build-exe** → Run → скачай артефакт `zapret-warp-windows`.

## Как это устроено

- Стратегии — `.bat`-файлы с командами `winws.exe`. Парсер `core/strategy.py`
  извлекает аргументы и подставляет **относительные** пути `bin/`, `lists/`
  (важно: nfqws понижает привилегии до nobody и читает файлы из своего cwd).
- Linux: `root-helper.sh` (sudo) → nftables-правила + `nfqws --daemon`.
- Windows: `winws.exe` напрямую (WinDivert перехватывает трафик).
- `wgcf/` + `bin/wgcf` + `bin/wireproxy` — встроенный WARP (WireGuard) для сетей,
  где UDP 2408 не блокируется провайдером. На «жёстких» сетях (как у автора)
  работает только официальный MASQUE-клиент, поэтому приложение по умолчанию
  управляет системным warp-cli.
