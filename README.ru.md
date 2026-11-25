# zapret-warp-gui

Кросс-платформенное приложение (Linux + Windows) с GUI и CLI:
**DPI-десинк (zapret) + Cloudflare WARP**. Десинк нужен, чтобы рукопожатие WARP
проходило в сетях, где режут или замедляют `*.cloudflareclient.com`; дальше всё
идёт через туннель WARP.

> English version: [README.md](README.md)

**Текущая версия: 1.3.0** — см. [CHANGELOG.md](CHANGELOG.md).

## Почему порядок важен

Сначала десинк, потом WARP. Без десинка TLS-рукопожатие с endpoint'ом WARP в
фильтрующей сети просто не завершается, и `warp-cli` висит в `Connecting`.
Приложение делает это само: `engine.start()` → `warp.connect()`.

## Быстрый старт

```bash
python cli.py doctor      # проверка готовности + точная команда, что доустановить
python cli.py start       # десинк (на Linux спросит sudo) + WARP
python cli.py status
python cli.py stop
python main.py            # GUI
```

Версия:

```bash
python cli.py --version
```

## Требования

**Linux**

```bash
sudo pacman -S tk nftables            # Arch
sudo apt install python3-tk nftables  # Debian/Ubuntu
```

* Нужен Cloudflare WARP (`warp-cli`) — `doctor` печатает команду установки для вашего
  дистрибутива.
* GUI запускается от **обычного пользователя** (root-окно не подключится к дисплею на
  Wayland). Привилегии для `nft`/`nfqws` идут через `root-helper.sh`:
  * из терминала — `sudo` спросит пароль в нём;
  * при запуске двойным кликом — один раз выполните `sudo python3 cli.py setup`
    (NOPASSWD только для `root-helper.sh`).

**Windows**

* Python 3.9+ (tkinter идёт в комплекте с официальным установщиком).
* Установленный Cloudflare WARP (`warp-cli.exe`).
* Запуск **от имени администратора**: `winws.exe` нужен драйвер WinDivert,
  `warp-cli` требует прав администратора.

## CLI

| Команда | Что делает |
|---|---|
| `doctor` | проверка окружения (бинари, списки, права, `warp-cli`, fooling) + как исправить |
| `status` | состояние десинка (с PID), активная стратегия и fooling, состояние WARP |
| `check` | снимок целиком: десинк, туннель, доступность 6 целей, выходной IP; код возврата 0/1 |
| `tune` | перебрать ~16 кандидатов и выбрать работающего на этой сети |
| `start` | десинк → WARP; печатает фактический `argv` |
| `stop` | отключить WARP, остановить десинк, убрать таблицу nft |
| `strategies` | список доступных `.bat`-стратегий |
| `setup` | (Linux) поставить NOPASSWD-правило для `root-helper.sh` |
| `key` | регистрация WARP-аккаунта через `wgcf` (нужен работающий десинк) |
| `--version` | печать версии |
| `--fooling <v>` | переопределить `config.json → fooling` на один запуск |
| `--timeout <с>` | таймаут одной пробы для `check` (по умолчанию 5) |
| `--no-probe` | `check` без сетевых проб |
| `-v` | дублировать лог в stderr |

`check` — честный ответ на вопрос «оно работает?»:

```text
DPI-десинк: запущен (pid 8124)
Стратегия:  warp_simple_fake.bat | fooling: md5sig
WARP:       Connected (Connected)
Выходной IP: 104.28.1.2  (colo FRA | warp=on)
Доступность:
  Cloudflare WARP: [OK] ok 214 мс
  YouTube: [OK] ok 209 мс
  Telegram: [OK] ok 321 мс
  Discord: [OK] ok 1175 мс
  Google 204: [OK] ok 624 мс
  DNS: [OK] ok 2 мс

Итог: работает
```

Проба возвращает **класс ошибки**, а не «да/нет»: `timeout` (блокировка),
`reset`/`tls_*` (**фейк дошёл до сервера** — не тот `fooling`), `refused`, `dns`.
Именно `reset`/`tls_*` на endpoint'е WARP — подпись бага, исправленного в 1.1.

Логи пишутся в `%LOCALAPPDATA%\zapret-warp\zapret-warp.log` (Linux:
`~/.local/state/zapret-warp/`), ротация 1 МБ × 3.

### Автоподбор стратегии

В репозитории 24 `.bat`-стратегии, и узнать, какая работает именно на вашей сети,
было нечем. `tune` перебирает их сам (20 кандидатов):

```bash
python cli.py tune --dry-run    # показать кандидатов (16), ничего не запускать
python cli.py tune              # прогон; нужны права администратора/root
python cli.py tune --apply      # сохранить победителя как strategies/tuned.bat
```

Кандидаты оцениваются по доле успеха, медиане RTT и **утечкам**: ответ `reset`/`tls_*`
означает, что фейк дошёл до сервера, поэтому «текущий» кандидат ставится ниже
чистого, даже если он быстрее. Бюджет по умолчанию — 180 с (`--budget`), попыток на
цель — 2 (`--attempts`). Техники: `fake`, `fake+multisplit`, `hostfakesplit`,
`multidisorder`, `fakedsplit` × `md5sig`/`md5sig,badseq`/`badseq`.

## Конфигурация (`config.json`, создаётся при первом запуске)

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `strategy` | `warp_simple_fake.bat` | `.bat` из `strategies/` |
| `interface` | `any` | исходящий интерфейс (Linux; `any` — все) |
| `fooling` | `auto` | значение `%Fooling%`: `auto` = `md5sig` на Windows, `ts,md5sig` на Linux. Можно любой список fooling из zapret (`md5sig`, `badseq`, `md5sig,badseq`, `ts`, …) |
| `gamefilter_tcp` / `gamefilter_udp` | `false` | подставить `%GameFilterTCP%`/`%GameFilterUDP%` игровыми диапазонами портов |
| `kill_engine_on_exit` | `true` | GUI привязывает `winws.exe` к Job Object — процесс умирает вместе с приложением |
| `warp_enabled` | `true` | подключать WARP после десинка |
| `warp_mode` | `warp` | `warp`, `warp+doh`, `doh`, `dot`, `warp+dot`, `proxy`, `tunnel_only` |
| `warp_protocol` | `MASQUE` | `MASQUE` или `WireGuard` |
| `warp_masque` | `h2-only` | `h3-with-h2-fallback`, `h3-only`, `h2-only` |
| `warp_endpoint` | `""` | свой endpoint (`warp-cli tunnel endpoint set`), пусто — сбросить |

## Маскировка: что именно делает стратегия и почему

Смысл в том, чтобы DPI не прочитал SNI `*.cloudflareclient.com` из рукопожатия WARP.
В версии 1.1 исправлены четыре вещи, из-за которых приложение было **заметнее**
обычного TLS:

| Параметр | Было | Стало | Почему |
|---|---|---|---|
| `--dpi-desync-fooling` | жёстко `ts` | `%Fooling%` → `md5sig` на Windows | `ts` требует включённых TCP timestamps, а в Windows они **выключены по умолчанию**. Без работающего fooling фейк доходит до реального сервера Cloudflare и ломает рукопожатие (та самая «вечная Connecting») |
| `--dpi-desync-repeats` | `8` | `2` | восемь байт-в-байт одинаковых ClientHello на соединение — это подпись, а не маскировка (плюс ~5,5 КБ мусора на соединение) |
| `--dpi-desync-fake-tls-mod` | не задан | `rnd,dupsid` | при явно заданном фейке zapret **отключает** свою рандомизацию `rnd,rndsni,dupsid`. `rnd` меняет `random`/`session_id` на каждый запрос, `dupsid` копирует настоящий session id — фейк выглядит ретрансмиссией |
| `--dpi-desync-cutoff` / `--dpi-desync-autottl` | нет | `n4` + autottl | дурение только первых пакетов; TTL подбирается так, чтобы фейк прошёл DPI, но не дошёл до сервера (не зависит от таймстампов) |

Область применения: в `lists/list-warp.txt` только хосты, относящиеся к туннелю
(`cloudflareclient.com`, `cloudflare-dns.com`, `one.one.one.one`). Широкий
`cloudflare.com` втянул бы в дурение все сайты за Cloudflare.

Ещё два факта, которые полезно знать:

* `lists/ipset-all.txt` **пуст намеренно** (раньше там лежал `203.0.113.113/32` —
  тестовый адрес из RFC 5737, поэтому все правила с `--ipset=` не совпадали ни с чем).
  Парсер теперь выбрасывает правила, у которых ipset был единственным ограничением:
  убрать только `--ipset=` было нельзя — `--filter-tcp=80,443,8443` остался бы без
  ограничения по адресам и задурил бы весь трафик. Заполните файл реальными CIDR —
  правила вернутся. Подробнее: [lists/README.md](lists/README.md).
* Стратегии — это `.bat` из апстрима zapret. Парсер (`core/strategy.py`) вычищает их
  артефакты копипасты: отдельный токен `-`, `%~dp0bin\` (неверный каталог) и строки
  `call service.bat` для скрипта, которого в этом репозитории нет.

## Структура проекта

```
main.py / cli.py          GUI (tkinter) и CLI
core/config.py            config.json
core/strategy.py          .bat → argv (кавычки, %BIN%, %LISTS%, %Fooling%, GameFilter, мёртвый ipset)
core/engine.py            winws.exe (Windows) / nfqws через root-helper.sh + nft (Linux)
core/probe.py             TLS/HTTP/DNS-пробы с классификацией ошибок
core/state.py             AppState + Monitor: единый источник состояния
core/warp.py              warp-cli: enum состояния, настройки, connect с реальными ошибками
core/winjob.py            Job Object: winws умирает вместе с GUI
core/logs.py              логи в файл с ротацией
core/wgcf.py              регистрация WARP-аккаунта (опционально, `cli.py key`)
core/doctor.py            отчёт о готовности (ASCII-иконки на узких консолях)
core/paths.py             портативно: рядом с .exe → _MEIPASS
root-helper.sh            привилегированные nft + запуск/остановка nfqws (Linux)
bin/                      nfqws, winws.exe, WinDivert, cygwin1.dll, фейки *.bin
lists/                    списки хостов/ipset (см. lists/README.md)
strategies/               .bat-стратегии из апстрима zapret
tests/                    pytest (проверяет реальные стратегии и списки)
```

* Windows: `winws.exe` + WinDivert; относительные `bin/`, `lists/` резолвятся от
  каталога приложения.
* Linux: `root-helper.sh` (sudo) создаёт таблицу `inet zapretunix`, затем запускает
  `nfqws --daemon --pidfile=/run/zapret-warp/nfqws.pid`. Порты и интерфейс проверяются
  до передачи в `nft`; остановка убивает только свой процесс (по pidfile), а не любой
  `nfqws` в системе.

## Windows: сборка .exe

PyInstaller не умеет кросс-компиляцию — собирайте на Windows (или через GitHub Actions).

```bat
pip install pyinstaller
pyinstaller zapret-warp.spec --noconfirm --clean
:: результат: dist\zapret-warp.exe, dist\zapret-warp-cli.exe
```

Один spec собирает два файла:

| Файл | Что это |
|---|---|
| `zapret-warp.exe` | GUI, сам просит права администратора (драйвер WinDivert) |
| `zapret-warp-cli.exe` | CLI: `check`, `status`, `doctor`, `tune`, `start`, `stop`. Намеренно **без** `uac_admin`, чтобы `status`/`check` работали без прав; для `start`/`tune` запускайте из терминала от администратора |

`zapret-warp.spec` кладёт внутрь `winws.exe`, `WinDivert.dll`, `WinDivert64.sys`,
`cygwin1.dll` (winws — Cygwin-сборка), `*.bin`, `lists/`, `strategies/`. Если рядом с
`.exe` положить папки `bin/ lists/ strategies/` — используются они (списки можно
править без пересборки).

Антивирус/SmartScreen может ругаться на бинарь: WinDivert — это драйвер перехвата
пакетов, к нему относятся настороженно. Если доверяете сборке — добавьте исключение
для папки приложения.

**Почему CLI — отдельный .exe:** `tune` и `check` живут в CLI, а сборка PyInstaller с
единственной точкой входа `main.py` файл `cli.py` не содержит (проверено: модуля
`core.tuner` в GUI-архиве не было).

## Тесты

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

Тесты гоняются по **реальным** `.bat` и спискам из репозитория, поэтому они защищают
и данные: нет имён стратегий, различающихся только регистром (из-за этого на Windows
терялся файл), не остаётся `%GameFilter%`, нет литерального `ts` в fooling, нет
мёртвых `--ipset`-правил, и `doctor` не падает на cp1251-консоли.

## Известные ограничения

* `nfqws` работает от **root** (ему нужен NFQUEUE). Так устроен апстрим zapret;
  приложение привилегии не понижает. `cli.py setup` откажется ставить NOPASSWD-правило,
  если `root-helper.sh` доступен на запись группе/остальным.
* Путь `wgcf` + `wireproxy` (WireGuard-WARP для сетей, где не блокируется UDP 2408)
  в 1.1 **не реализован** — этих бинарей нет в `bin/`. Используется только официальный
  транспорт `warp-cli`.
* WARP — один домен и один ASN. Если `cloudflareclient.com` блокируют по IP, десинк
  не поможет.

## Если не работает

| Симптом | Вероятная причина | Что делать |
|---|---|---|
| WARP висит на `Connecting` / 51 % | фейки дошли до сервера (fooling не работает) | посмотрите `fooling` в `doctor`; на Windows — `md5sig` или включите таймстампы |
| `winws.exe завершился с кодом …` | нет прав администратора / WinDivert блокирует антивирус | запуск от админа, исключение в Defender |
| `file_open_test: cannot access hostlist file` | неверный рабочий каталог | запускайте через приложение, а не копируйте команду руками |
| WARP подключён, сайты не открываются | режут сам WARP, десинк не применяется | сверьте hostlist стратегии с endpoint из `warp-cli settings` |
| `doctor` печатает `[OK]`/`[!!]` | консоль не умеет эмодзи (cp1251) | это нормально, вывод корректный |
| `nfqws: unknown option --dpi-desync-fake-tls-mod` | старая сборка nfqws в `bin/` | уберите `--dpi-desync-fake-tls-mod` из `strategies/warp_simple_fake.bat`; бинарь в комплекте сжат UPX, поэтому его возможности заранее не проверить |
