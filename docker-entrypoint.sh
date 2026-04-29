#!/usr/bin/env bash
set -euo pipefail

wait_for_cups() {
    local tries=0
    while [ "$tries" -lt 30 ]; do
        if lpstat -r 2>/dev/null | grep -q "scheduler is running"; then
            return 0
        fi
        tries=$((tries + 1))
        sleep 0.5
    done
    echo "WARNING: CUPS scheduler did not start within 15 seconds" >&2
    return 1
}

setup_cups_printer() {
    local name="${CUPS_LPADMIN_NAME:-}"
    local desc="${CUPS_LPADMIN_DESC:-}"
    local uri="${CUPS_LPADMIN_PRINTER:-}"

    if [ -z "$uri" ]; then
        return 0
    fi

    [ -n "$name" ] || name="Printer"
    [ -n "$desc" ] || desc="Auto-configured printer"

    lpadmin -p "$name" -E -v "$uri" -m raw -D "$desc" 2>/dev/null \
        && lpadmin -d "$name"
}

if [ "${CUPS_ENABLED:-false}" = "true" ]; then
    mkdir -p /run/cups /var/log/cups /var/spool/cups/tmp
    /usr/sbin/cupsd -s /etc/cups/cups-files.conf 2>/dev/null || /usr/sbin/cupsd
    wait_for_cups
    setup_cups_printer
fi

exec "$@"
