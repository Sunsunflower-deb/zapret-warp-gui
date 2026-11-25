# Измерения до / после

Заполняется по протоколу из плана (§7.3) на **живой сети**. В репозитории лежит только
шаблон: цифры здесь должны быть вашими, с датой, версией и названием сети.

Зачем это нужно: правки 1.1 меняют поведение обхода. Без замера «до» невозможно
отличить «стало лучше» от «стало иначе», а на разных сетях результат отличается.

## Как мерить

```bash
# 1. Что вообще запущено и с какими параметрами
python cli.py status
warp-cli settings            # фактический endpoint/режим
python cli.py doctor         # fooling, права, списки

# 2. Доля успешных подключений (20 попыток)
for i in $(seq 20); do ... warp-cli connect ...; done   # см. скрипт ниже

# 3. Пробы TLS к endpoint (классификация ошибок)
python - <<'PY'
from core import probe
# хост возьмите из `warp-cli settings` (endpoint туннеля)
print(probe.probe("cloudflareclient.com", verify=False))
PY

# 4. Linux: правила и права
nft list ruleset | sed -n '/zapretunix/,/}/p'
ps -o user=,pid=,args= -p "$(cat /run/zapret-warp/nfqws.pid)"

# 5. Утечки: при включённом WARP должен быть IP Cloudflare
curl -s https://www.cloudflare.com/cdn-cgi/trace | grep -E '^(ip|colo|warp)='
```

## Шаблон

### Сеть: <домашний Wi-Fi / мобильный оператор / ...>, дата: ГГГГ-ММ-ДД

| Метрика | До (что было) | После 1.1 | Комментарий |
|---|---|---|---|
| Успешных `warp-cli connect` из 20 | | | |
| Медиана времени до `Connected`, с | | | |
| Пробы endpoint: `ok` / `timeout` / `reset` / `tls_*` | | | `reset`/`tls_*` = фейк дошёл до сервера |
| Байт фейков на соединение (`repeats` × размер) | ~5,6 КБ | ~1,4 КБ | считается из argv |
| Зелёных проверок доступности (из 6) | | | YouTube/Telegram/Discord/Google/DNS/Cloudflare |
| `fooling`, с которым заработало | `ts` | `md5sig` | |

### Выводы

* Что изменилось и почему (по фактическим цифрам, а не по ощущениям).
* Какие параметры пришлось переопределить на этой сети (`fooling`, стратегия).
