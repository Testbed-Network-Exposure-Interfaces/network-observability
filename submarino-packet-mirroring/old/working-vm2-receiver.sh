#!/bin/bash
# VM2 - Packet Receiver & TAP Injector
# Listens on a TCP socket, receives a pcap stream from VM1,
# and injects packets into a TAP interface via inject.py.
# Resilient: recreates TAP and re-listens on failure, safe for use as a systemd service.

set -euo pipefail

: "${TAP_DEV:?Environment variable TAP_DEV is required - specify the TAP device name to create/use, e.g., tap1}"
: "${TAP_IP:?Environment variable TAP_IP is required - specify the IP address with CIDR for the TAP device, e.g., 10.99.0.1/24}"
: "${LISTEN_PORT:?Environment variable LISTEN_PORT is required - specify the TCP port to listen on, e.g., 9999}"
: "${RETRY_INTERVAL:?Environment variable RETRY_INTERVAL is required - specify number of seconds to wait before retrying connection}"
: "${INJECT_SCRIPT:?Environment variable INJECT_SCRIPT is required - specify the full path to the packet injection script, e.g., /opt/inject.py}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [vm2-receiver] $*" | sudo tee -a /var/log/vm2_receiver.log
}

setup_tap() {
    # Idempotent: only create tap if it doesn't already exist.
    if ! ip link show "$TAP_DEV" &>/dev/null; then
        log "Creating TAP device $TAP_DEV..."
        ip tuntap add dev "$TAP_DEV" mode tap
        ip addr add "$TAP_IP" dev "$TAP_DEV"
        log "TAP device $TAP_DEV created with IP $TAP_IP."
    else
        log "TAP device $TAP_DEV already exists, skipping creation."
    fi

    # Always ensure it's up.
    ip link set "$TAP_DEV" up
    log "TAP device $TAP_DEV is up."
}

log "Starting receiver on port $LISTEN_PORT -> $TAP_DEV"

# Ensure TAP exists before entering the loop (survives VM reboots cleanly).
setup_tap
source /home/ubuntu/venv/bin/activate

while true; do
    log "Listening on port $LISTEN_PORT..."


    # socat accepts one TCP connection at a time and pipes the pcap stream
    # into inject.py. When the sender disconnects, socat exits, inject.py
    # gets EOF, and we loop back to listen again — no manual intervention needed.
    if nc -l -p "$LISTEN_PORT"  \
        | python3 "$INJECT_SCRIPT"; then
        log "inject.py exited cleanly."
    else
        log "inject.py or socat exited with error (code $?)."
    fi

    # Re-verify TAP is still up (e.g. after a kernel hiccup).
    setup_tap

    log "Restarting listener in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done
