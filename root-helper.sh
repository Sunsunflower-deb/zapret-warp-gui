#!/usr/bin/env bash
# =============================================================================
# Привилегированный помощник zapret-warp (Linux).
# Настройка nftables + запуск/остановка nfqws от root.
#
# Вызывается из приложения:
#   root-helper.sh start <TCP_PORTS> <UDP_PORTS> <IFACE> [nfqws args...]
#   root-helper.sh stop
#
# Для работы GUI без пароля выполни один раз:
#   sudo python3 cli.py setup      (создаёт NOPASSWD-правило в /etc/sudoers.d)
# =============================================================================
set -u

PROG_DIR="$(cd "$(dirname "$0")" && pwd)"
NFQWS="$PROG_DIR/bin/nfqws"
MARK="0x40000000"
QNUM="220"

action="${1:-}"

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

case "$action" in
    start)
        if [ "$#" -lt 4 ]; then
            echo "использование: root-helper.sh start TCP UDP IFACE [ARGS...]" >&2
            exit 2
        fi
        tcp_ports="$2"; udp_ports="$3"; iface="$4"
        shift 4
        pkill -f nfqws 2>/dev/null || true
        fw_setup "$tcp_ports" "$udp_ports" "$iface"
        cd "$PROG_DIR"
        echo "[root-helper] uid=$(id -u) user=$(id -un) nfqws=$NFQWS" >&2
        # пути списков теперь относительные (bin/, lists/) — nfqws читает их из
        # своего cwd даже после понижения привилегий до nobody (домашний каталог 700)
        exec "$NFQWS" --daemon --dpi-desync-fwmark="$MARK" --qnum="$QNUM" "$@"
        ;;
    stop)
        pkill -f nfqws 2>/dev/null || true
        fw_clear
        ;;
    status)
        if pgrep -f nfqws >/dev/null 2>&1; then echo "running"; else echo "stopped"; fi
        ;;
    *)
        echo "неизвестное действие: $action" >&2
        exit 2
        ;;
esac
