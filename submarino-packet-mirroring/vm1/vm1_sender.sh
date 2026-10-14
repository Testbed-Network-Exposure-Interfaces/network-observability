#!/bin/bash
# VM1 (source) - Packet Sender
# Captures packets on a given interface and streams them to a destination VM via TCP socket.
# Permissions provided through systemd service: CAP_NET_RAW (no sudo required).

set -euo pipefail

: "${IFACE:?Environment variable IFACE is required - specify the network interface to capture packets from, e.g., eth0}"
: "${DEST_HOST:?Environment variable DEST_HOST is required - specify the IP address to send packets to on the destination VM, e.g. 192.168.1.10}"
: "${DEST_PORT:?Environment variable DEST_PORT is required - specify the TCP port to connect to on the destination VM, e.g., 9999}"
: "${RETRY_INTERVAL:?Environment variable RETRY_INTERVAL is required - specify number of seconds to wait before retrying connection, e.g. 10}"


log() {
    echo "[$IFACE-sender] $*"
}

log "Starting sender on interface '$IFACE' -> $DEST_HOST:$DEST_PORT"

while true; do
    log "Attempting to connect to $DEST_HOST:$DEST_PORT..."

    # tcpdump streams pcap to stdout; socat forwards it to destination VM.
    # If either dies, the pipe breaks and we retry after RETRY_INTERVAL.
    if tcpdump -i "$IFACE" -U -w - | socat - TCP:"$DEST_HOST":"$DEST_PORT"; then
        log "Connection closed cleanly."
    else
        log "Connection lost. [tcpdump=${PIPESTATUS[0]} | socat=${PIPESTATUS[1]}]"
    fi

    log "Retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done
