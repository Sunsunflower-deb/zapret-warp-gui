@echo off
:: ================================================================
:: zapret-warp: WARP-only strategy (Simple Fake)
:: Desync is applied ONLY to Cloudflare WARP hosts on HTTPS ports
:: (cloudflareclient.com, cloudflare.com, 1.1.1.1 DoH etc).
:: Everything else is left untouched: with full-tunnel WARP active
:: the remaining traffic is already encapsulated inside the tunnel,
:: extra desync would only add overhead and latency.
:: Fits MASQUE h2-only (TCP 443). A QUIC/UDP-443 rule is included
:: in case h3/QUIC transport is used later.
:: NOTE: ignores GameFilter checkboxes (no game-port rules here).
:: Select it in GUI "Strategies" or set config.json -> "strategy".
:: ================================================================

set "BIN=%~dp0bin\"
set "LISTS=%~dp0lists\"
cd /d %BIN%

start "zapret-warp" /min "%BIN%winws.exe" --wf-tcp=443,2053,2083,2087,2096,8443 --wf-udp=443 ^
--filter-tcp=443,2053,2083,2087,2096,8443 --hostlist="%LISTS%list-warp.txt" --dpi-desync=fake --dpi-desync-repeats=8 --dpi-desync-fooling=ts --dpi-desync-fake-tls="%BIN%tls_clienthello_www_google_com.bin" --new ^
--filter-udp=443 --hostlist="%LISTS%list-warp.txt" --dpi-desync=fake --dpi-desync-repeats=8 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --dpi-desync-any-protocol=1
