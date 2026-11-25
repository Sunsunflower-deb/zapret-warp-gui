#!/usr/bin/env bash
# =============================================================================
# Привилегированный помощник zapret-warp (Linux).
# Настройка nftables + запуск/остановка nfqws от root.
#
# Вызывается из приложения:
#   root-helper.sh start <TCP_PORTS> <UDP_PORTS> <IFACE> [nfqws args...]
#   root-helper.sh stop
#   root-helper.sh status
#
# Для работы GUI без пароля выполни один раз:
#   sudo python3 cli.py setup      (создаёт NOPASSWD-правило в /etc/sudoers.d)
#
# ВАЖНО: nfqws запускается от root (ему нужны NFQUEUE и raw-сокеты) —
# привилегии НЕ понижаются. Списки (lists/), которые он читает, должны быть
# доступны на чтение; относительные пути в argv резолвятся от PROG_DIR.
# =============================================================================
set -u

PROG_DIR="$(cd "$(dirname "$0")" && pwd)"
NFQWS="$PROG_DIR/bin/nfqws"
MARK="0x40000000"
QNUM="220"
PIDFILE="/run/zapret-warp/nfqws.pid"

action="${1:-}"

valid_ports() {
    # пусто допустимо; иначе только цифры, запятые и диапазоны через дефис
    case "${1:-}" in
        '') return 0 ;;
        *[!0-9,-]*) return 1 ;;
        *) return 0 ;;
    esac
}

valid_iface() {
    case "${1:-}" in
        '') return 0 ;;
        *[!A-Za-z0-9_.:@-]*) return 1 ;;
        *) return 0 ;;
    esac
}

fw_clear() {
    nft delete table inet zapretunix 2>/dev/null || true
}

fw_setup() {
    local tcp_ports="$1" udp_ports="$2" iface="$3"
    fw_clear
    nft add table inet zapretunix
    nft add chain inet zapretunix post '{' type filter hook postrouting priority 'mangle;' '}'
    nft add chain inet zapretunix pre  '{' type filter hook prerouting  priority 'filter;' '}'

    local oif=() iif=()
    if [ -n "$iface" ] && [ "$iface" != "any" ]; then
        oif=(oifname "$iface")
        iif=(iifname "$iface")
    fi

    if [ -n "$tcp_ports" ]; then
        nft add rule inet zapretunix post "${oif[@]}" meta mark and "$MARK" == 0 \
            tcp dport "{$tcp_ports}" ct original packets 1-6 queue num "$QNUM" bypass
    fi
    if [ -n "$udp_ports" ]; then
        nft add rule inet zapretunix post "${oif[@]}" meta mark and "$MARK" == 0 \
            udp dport "{$udp_ports}" ct original packets 1-6 queue num "$QNUM" bypass
    fi
    if [ -n "$tcp_ports" ]; then
        nft add rule inet zapretunix pre "${iif[@]}" \
            tcp sport "{$tcp_ports}" ct reply packets 1-3 queue num "$QNUM" bypass
    fi
}

kill_own() {
    # Останавливаем ТОЛЬКО свой nfqws: по pidfile, с мягким фолбэком на
    # путь bin/nfqws (чтобы не убить чужой nfqws/роутерный инстанс).
    local pid=""
    if [ -r "$PIDFILE" ]; then
        pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    fi
    case "$pid" in
        ''|*[!0-9]*) pid="" ;;
    esac
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        sleep 0.2
        kill -9 "$pid" 2>/dev/null || true
    else
        pkill -f "$PROG_DIR/bin/nfqws" 2>/dev/null || true
    fi
    rm -f "$PIDFILE" 2>/dev/null || true
}

case "$action" in
    start)
        if [ "$#" -lt 4 ]; then
            echo "использование: root-helper.sh start TCP UDP IFACE [ARGS...]" >&2
            exit 2
        fi
        tcp_ports="$2"; udp_ports="$3"; iface="$4"
        if ! valid_ports "$tcp_ports" || ! valid_ports "$udp_ports"; then
            echo "root-helper: недопустимые порты (ожидаются цифры, ',' и '-')" >&2
            exit 2
        fi
        if ! valid_iface "$iface"; then
            echo "root-helper: недопустимое имя интерфейса: $iface" >&2
            exit 2
        fi
        if [ ! -x "$NFQWS" ]; then
            echo "root-helper: не найден исполняемый $NFQWS" >&2
            exit 3
        fi
        shift 4
        kill_own
        install -d -m 0755 /run/zapret-warp 2>/dev/null || true
        fw_setup "$tcp_ports" "$udp_ports" "$iface"
        cd "$PROG_DIR" || exit 3
        echo "[root-helper] uid=$(id -u) user=$(id -un) nfqws=$NFQWS" >&2
        exec "$NFQWS" --daemon --pidfile="$PIDFILE" \
            --dpi-desync-fwmark="$MARK" --qnum="$QNUM" "$@"
        ;;
    stop)
        kill_own
        fw_clear
        ;;
    status)
        pid=""
        if [ -r "$PIDFILE" ]; then pid="$(cat "$PIDFILE" 2>/dev/null || true)"; fi
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "running"
        else
            echo "stopped"
        fi
        ;;
    *)
        echo "неизвестное действие: $action" >&2
        exit 2
        ;;
esac
