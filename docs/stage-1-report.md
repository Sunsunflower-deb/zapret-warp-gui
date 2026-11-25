# Отчёт по этапу 1 (релиз 1.1.0)

Короткая сводка: что сделано по плану, что проверено, что осталось. Подробности по
изменениям — в [CHANGELOG.md](../CHANGELOG.md).

## Статус задач плана

| ID | Задача | Статус | Где |
|---|---|---|---|
| 0.1 | venv, ruff, pytest-каркас | ✅ | `pyproject.toml`, `requirements-dev.txt` |
| 0.2 | Тесты парсера на фикстурах | ✅ | `tests/` (121 тест) |
| 0.3 | Baseline-замеры на живой сети | ⏳ **нужна ваша сеть** | шаблон: [measurements.md](measurements.md) |
| 1.1 | Плейсхолдер `%Fooling%` | ✅ | `core/strategy.py`, `core/config.py`, все `.bat` |
| 1.2 | `ensure_tcp_timestamps()` + `preferred_fooling` | ✅ | `core/engine.py` (`ensure_tcp_timestamps`) |
| 1.3 | Убрать статический фейк / добавить `fake-tls-mod` | ✅ | `strategies/warp_simple_fake.bat` |
| 1.4 | `repeats` 8→2, `cutoff`, `autottl` | ✅ | там же |
| 1.5 | Мёртвые ipset-правила | ✅ | `lists/ipset-all.txt`, `core/strategy.py::_prune_dead_ipset` |
| 1.6 | GameFilter без мусорных правил | ✅ | `core/strategy.py::_apply_gamefilter` |
| 1.7 | Артефакты `.bat` (service.bat, `%~dp0bin\`, `-`) | ✅ | все 24 стратегии |
| 1.8 | Валидация в helper, pidfile, stop только своего процесса | ⚠️ частично | `root-helper.sh`, `core/engine.py`; `--user=nobody` **не** делали (см. ниже) |
| 1.9 | Комментарий про «понижение привилегий» | ✅ | `core/strategy.py` |
| 1.10 | README ↔ код | ✅ | `README.md`, `README.ru.md`, `lists/README.md` |
| 1.11 | Версия, `--version`, CHANGELOG | ✅ | `core/version.py`, `cli.py`, `main.py` |

Дополнительно (найдено по ходу, в план не входило):

* **Коллизия регистра в стратегиях**: `general_SIMPLE_FAKE.bat` и
  `general_simple_fake.bat` — на Windows git терял один файл, стратегия молча
  исчезала из списка. Переименовано в `general_simple_fake_stun.bat`, теперь 24
  уникальных имени.
* **`cli.py doctor` падал на русской Windows** (`UnicodeEncodeError`, cp1251 не умеет
  `✅`/`→`). Теперь ASCII-иконки + `stdio` с заменой ошибок кодирования.
* **`engine._pid_alive()` убивал процесс на Windows**: `os.kill(pid, 0)` там не
  проверка, а `TerminateProcess`. Функция теперь POSIX-only.
* **`.gitattributes`**: `*.sh` — LF, `*.bat` — CRLF, `bin/*` — бинарные. Иначе
  `root-helper.sh` с CRLF не запускается на Linux.

## Что проверено

* `python -m ruff check .` — чисто.
* `python -m pytest -q` — **121 passed, 4 skipped** (skip — POSIX-only проверки прав на
  Windows).
* `python cli.py --version` → `zapret-warp 1.1.0`.
* `python cli.py doctor` — работает на живой cp1251-консоли, показывает фактический
  `fooling` (`md5sig  (config: auto)`).
* `python cli.py strategies` — 24 уникальных имени.
* `python -c "import main"` — GUI-модуль импортируется.
* `bash -n root-helper.sh` — синтаксис валиден.
* **Флаги в `winws.exe` реально есть.** Бинарь из `bin/` знает всё, что мы теперь
  используем: `--dpi-desync-fake-tls-mod` (и модификаторы `rndsni`, `dupsid`,
  `padencap`), `--dpi-desync-autottl`, `--dpi-desync-cutoff`, `--dpi-desync-repeats`,
  `--dpi-desync-fooling`, режимы `hostfakesplit`, `multisplit`, `multidisorder`,
  `fakedsplit`, `fakeddisorder`, а также `--dpi-desync-fake-wireguard`,
  `--hostlist-auto` и `--ssid-filter`. Проверено чтением строк бинаря и закреплено
  тестом `tests/test_binaries.py`.
* **`nfqws` (Linux) проверить так нельзя**: он сжат UPX, строки недоступны. Если
  какая-то старая сборка не знает `--dpi-desync-fake-tls-mod`, nfqws стартует с
  ошибкой — тогда этот флаг надо убрать из WARP-стратегии (см. «Если не работает»
  в README). Полноценный capability probing — задача 3.1.
* Фактический argv WARP-стратегии:

```
--wf-tcp=443,2053,2083,2087,2096,8443 --wf-udp=443
--filter-tcp=... --hostlist=lists/list-warp.txt --dpi-desync=fake
--dpi-desync-repeats=2 --dpi-desync-fooling=md5sig --dpi-desync-autottl
--dpi-desync-cutoff=n4 --dpi-desync-fake-tls=bin/tls_clienthello_www_google_com.bin
--dpi-desync-fake-tls-mod=rnd,dupsid
--new --filter-udp=443 --hostlist=lists/list-warp.txt --dpi-desync=fake
--dpi-desync-repeats=2 --dpi-desync-fake-quic=bin/quic_initial_www_google_com.bin
--dpi-desync-any-protocol=1
```

## Что НЕ проверено (нужен живой запуск)

Автотесты проверяют разбор и данные, но не сеть. На вашей машине стоит прогнать:

1. `python cli.py start` от администратора → дошло ли до `WARP: connect выполнен`.
2. Заполнить [measurements.md](measurements.md) «до/после» (особенно важно для гипотезы
   про `ts` → `md5sig`: это главный кандидат на причину «висит на Connecting»).
3. Если на сети работает только старый вариант — переключить `fooling` в GUI на `ts`
   (или `md5sig,badseq`), это и есть предусмотренный откат.

## Отклонения от плана и почему

* **`--user=nobody` для nfqws не включён.** nfqws пишет `--pidfile` в
  `/run/zapret-warp/` (каталог root-owned), порядок «демонизация → pidfile → сброс
  привилегий» в апстриме не документирован, а проверить это без Linux-машины нельзя.
  Включать вслепую — риск сломать остановку и чтение списков. Вместо этого: убрана
  ложь в комментарии (1.9), а переход на polkit/понижение прав — этап 7.
* **`--dpi-desync-autottl` добавлен только в TCP-правило**: для UDP нет SYN/ACK, на
  котором autottl считает длину пути; UDP-правило оставлено как было (кроме
  `repeats`).
* **`general_*.bat` правились автоматом** (23 файла): замена только токена `ts` в
  `--dpi-desync-fooling`, где он реально был; стратегии с `badseq` не тронуты.

## Следующий шаг

Этап 2 плана: `core/probe.py` (TLS/HTTP-пробы с классификацией ошибок), `Monitor` с
`AppState`, разбор `warp-cli status` в enum, логи в файл. Без этого нельзя ни
автоподбор (этап 6), ни watchdog (этап 5), ни честная панель доступности.
