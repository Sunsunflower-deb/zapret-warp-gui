@echo off
:: ================================================================
:: zapret-warp: WARP-only strategy (маскировка вместо пачки фейков)
:: Десинк применяется ТОЛЬКО к хостам Cloudflare WARP на HTTPS-портах.
:: Остальное не трогаем: при full-tunnel WARP этот трафик уже внутри
:: туннеля, лишнее дурение добавляет только задержку.
::
:: Почему параметры такие:
::  * --dpi-desync-repeats=2 -- раньше было 8. Восемь байт-в-байт
::    одинаковых ClientHello на каждое соединение -- готовая сигнатура
::    (плюс ~5.5 КБ мусора на соединение).
::  * --dpi-desync-fake-tls-mod=rnd,dupsid -- при явно заданном фейке zapret
::    отключает рандомизацию по умолчанию (rnd,rndsni,dupsid). rnd меняет
::    random/session_id на каждый запрос, dupsid копирует session_id из
::    настоящего ClientHello, чтобы фейк выглядел ретрансмиссией.
::  * --dpi-desync-autottl -- TTL подбирается так, чтобы фейк прошёл через
::    DPI, но не дошёл до сервера. Не зависит от TCP timestamps, которые
::    в Windows выключены по умолчанию (из-за этого старый fooling=ts на
::    Windows не работал, и фейки уходили в реальный Cloudflare).
::  * --dpi-desync-cutoff=n4 -- дурение только первых пакетов соединения.
::  * %Fooling% -- подставляется движком (config.json -> "fooling"):
::    "auto" = md5sig на Windows, "ts,md5sig" на Linux.
::
:: Файл рассчитан и на запуск из GUI (парсер сам подставляет пути), и на
:: запуск двойным кликом: ~dp0 -- это strategies\, поэтому bin/ и lists/
:: лежат на уровень выше.
:: ================================================================

set "BIN=%~dp0..\bin\"
set "LISTS=%~dp0..\lists\"
:: значение по умолчанию для прямого запуска .bat (GUI подставляет своё)
if not defined Fooling set "Fooling=md5sig"
cd /d "%BIN%"

start "zapret-warp" /min "%BIN%winws.exe" --wf-tcp=443,2053,2083,2087,2096,8443 --wf-udp=443 ^
--filter-tcp=443,2053,2083,2087,2096,8443 --hostlist="%LISTS%list-warp.txt" --dpi-desync=fake --dpi-desync-repeats=2 --dpi-desync-fooling=%Fooling% --dpi-desync-autottl --dpi-desync-cutoff=n4 --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --dpi-desync-fake-tls-mod=rnd,dupsid --new ^
--filter-udp=443 --hostlist="%LISTS%list-warp.txt" --dpi-desync=fake --dpi-desync-repeats=2 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --dpi-desync-any-protocol=1
