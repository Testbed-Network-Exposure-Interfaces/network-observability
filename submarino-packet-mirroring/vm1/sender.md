# Packet Sender to destination VM — Setup Guide

### Verify Dependencies
```sh
sudo apt install socat tcpdump -y
which socat 
which tcpdump
```

### Setup

Create system user account named packet-sender without login access. It will be used in systemd services to avoid running the scripts as root. The permissions are provided in the systemd service specification. Therefore, you may skip this step and use a user you want if for some reason you don't want to create this one.
```sh
sudo useradd -r -s /sbin/nologin packet-sender
``` 

Create file script at the specified path. With vim: `sudo vim /usr/local/bin/metrics_sender.sh`

```sh
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

```


Change permissions of the recently created file (root: rwx; packet-sender: r-x, others ---)
```
sudo chown root:packet-sender /usr/local/bin/metrics_sender.sh
sudo chmod 750 /usr/local/bin/metrics_sender.sh
```

Two systemd services will need to be created, one for each interface we want to monitor. Create two services, replacing <iface1\> and <iface2\> with the monitored interface name for readability. The corresponding service spec is also provided bellow.
```sh
sudo vim /etc/systemd/system/metrics_<iface1>_sender.service
sudo cp /etc/systemd/system/metrics_<iface1>_sender.service /etc/systemd/system/metrics_<iface2>_sender.service
```
```sh
[Unit]
Description=Packet Sender to destination VM
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
User=packet-sender
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
ExecStart=/usr/local/bin/metrics_sender.sh
Environment="IFACE="
Environment="DEST_HOST="
Environment="DEST_PORT="
Environment="RETRY_INTERVAL=10"

[Install]
WantedBy=multi-user.target

```

Change the environment variables IFACE, DEST_HOST, DEST_PORT passed in the service specs. IFACE should be different for each service for each of the monitored interfaces. DEST_HOST is provided by rdireito and the same in both specs. For DEST_PORT you may use ports 9998 and 9999 for <iface1\> and <iface2\>, respectively.
```sh
sudo vim /etc/systemd/system/metrics_<iface1>_sender.service
sudo vim /etc/systemd/system/metrics_<iface2>_sender.service
```

Reload systemd so it picks up the new service specs.
```sh
sudo systemctl daemon-reload
```

Enable the services so they start on boot
```sh
sudo systemctl enable metrics_<iface1>_sender.service
sudo systemctl enable metrics_<iface2>_sender.service
```

Start the services now
```sh
sudo systemctl start metrics_<iface1>_sender.service
sudo systemctl start metrics_<iface2>_sender.service
```

Verify they are running
```sh
sudo systemctl status metrics_<iface1>_sender.service
sudo systemctl status metrics_<iface2>_sender.service
```

Watch the logs. The logs may indicate connection retries if the receiver on the destination VM is not configured yet.
```sh
journalctl -u metrics_<iface1>_sender.service -f
journalctl -u metrics_<iface2>_sender.service -f
```

