#!/bin/bash
# VM1 - Packet Sender
# Captures packets on a given interface and streams them to VM2 via TCP socket.
# Resilient: retries on failure, safe for use as a systemd service.

set -euo pipefail

: "${IFACE:?Environment variable IFACE is required - specify the network interface to capture packets from, e.g., eth0}"
: "${VM2_HOST:?Environment variable VM2_HOST is required - specify the IP address of VM2 to send packets to}"
: "${VM2_PORT:?Environment variable VM2_PORT is required - specify the TCP port on VM2 to connect to, e.g., 9999}"
: "${RETRY_INTERVAL:?Environment variable RETRY_INTERVAL is required - specify number of seconds to wait before retrying connection}"


log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [vm1-sender] $*" | sudo tee -a /var/log/vm1_sender.log
}

log "Starting sender on interface '$IFACE' -> $VM2_HOST:$VM2_PORT"

while true; do
    log "Attempting to connect to $VM2_HOST:$VM2_PORT..."


    # tcpdump streams pcap to stdout; socat forwards it to VM2.
    # If either dies, the pipe breaks and we retry after RETRY_INTERVAL.
    if sudo tcpdump -i "$IFACE" -w - -U  \
        | nc $VM2_HOST $VM2_PORT; then
        log "Connection closed cleanly."
    else
        log "Connection lost or failed (exit code $?)."
    fi

    log "Retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done