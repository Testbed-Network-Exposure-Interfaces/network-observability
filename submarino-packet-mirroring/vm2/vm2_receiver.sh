#!/bin/bash
# VM2 - Packet Receiver & TAP Injector
# Listens on a TCP socket, receives a pcap stream from VM1,
# and injects packets into a TAP interface via inject.py.
# Permissions provided through systemd service: CAP_NET_RAW (no sudo required).

set -euo pipefail

: "${TAP_DEV:?Environment variable TAP_DEV is required - specify the TAP device name to create/use, e.g., tap1}"
: "${LISTEN_PORT:?Environment variable LISTEN_PORT is required - specify the TCP port to listen on, e.g., 9999}"
: "${VENV_PY_PATH:?Environment variable VENV_PY_PATH is required - specify the path to the Python interpreter in the virtual environment, e.g., /opt/venv/bin/python}"
: "${INJECT_SCRIPT:?Environment variable INJECT_SCRIPT is required - specify the full path to the packet injection script, e.g., /opt/inject.py}"
: "${RETRY_INTERVAL:?Environment variable RETRY_INTERVAL is required - specify number of seconds to wait before retrying connection}"

log() {
    echo "[$TAP_DEV-receiver] $*"
}

log "Starting receiver on port $LISTEN_PORT -> $TAP_DEV"

while true; do
    log "Listening on port $LISTEN_PORT..."

    # socat accepts one TCP connection at a time and processes the pcap stream with inject.py.
    # if failure occurs in either, we log the error and retry after RETRY_INTERVAL.
    if socat TCP-LISTEN:"$LISTEN_PORT",reuseaddr EXEC:"$VENV_PY_PATH \"$INJECT_SCRIPT\" $TAP_DEV"; then
        log "inject.py exited cleanly."
    else
        log "inject.py or socat exited with error (code $?)."
    fi

    log "Restarting listener in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done
