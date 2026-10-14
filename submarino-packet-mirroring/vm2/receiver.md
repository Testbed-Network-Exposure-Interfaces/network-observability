# Packet Receiver and Tap interface injector — Setup Guide

### Verify Dependencies
```sh
sudo apt install socat tcpdump python3 -y
which socat
which tcpdump
which python3
```

### Setup

Create tap interfaces through which the packets will be received. One interface will be created for each of the interfaces being monitored in the source VM (two in total).
```sh
sudo ip tuntap add dev tap0 mode tap
sudo ip link set tap0 up
#sudo ip addr add 10.99.0.1/24 dev tap0
sudo ip tuntap add dev tap1 mode tap
sudo ip link set tap1 up
#sudo ip addr add 10.99.1.1/24 dev tap1
```

Create system user account named packet-receiver without login access. It will be used in systemd services to avoid running the scripts as root. The permissions are provided in the systemd service specification.
```sh
sudo useradd -r -s /sbin/nologin packet-receiver
``` 

Make directory which will contain the bash script, the python script, the python environment and its requirements.
```sh
sudo mkdir /usr/local/bin/mrecv/
```

Create the python virtual environment and register its dependencies on a requirements.txt file.
```sh
sudo python3 -m venv /usr/local/bin/mrecv/venv
echo "scapy==2.7.0" | sudo tee -a /usr/local/bin/mrecv/requirements.txt
sudo /usr/local/bin/mrecv/venv/bin/python -m pip install -r /usr/local/bin/mrecv/requirements.txt
```

Create file script at the specified path. With vim: `sudo vim /usr/local/bin/mrecv/metrics_receiver.sh`
```sh
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

```

Create python script to inject the socket received packets through the newly created tap interfaces. With vim: `sudo vim /usr/local/bin/mrecv/inject_scapy.py`
```py
#!/usr/bin/env python3
import sys
import struct
import fcntl
from scapy.all import PcapReader

# This script reads packets from a pcap stream on stdin and injects them into a specified TAP device.
if len(sys.argv) < 2:
    print("Usage: inject.py <tap_dev>", file=sys.stderr)
    sys.exit(11)

tap_dev = sys.argv[1]

# Open TAP device
tap = open('/dev/net/tun', 'r+b', buffering=0)
TUNSETIFF = 0x400454ca
IFF_TAP   = 0x0002
IFF_NO_PI = 0x1000
ifr = struct.pack('16sH', tap_dev.encode(), IFF_TAP | IFF_NO_PI)
fcntl.ioctl(tap, TUNSETIFF, ifr)

# Read packets from stdin stream and inject
with PcapReader(sys.stdin.buffer) as reader:
    for pkt in reader:
        tap.write(bytes(pkt))

```

Change permissions of the recently created files (root: rwx; packet-sender: r-x, others r--)
```sh
sudo chown root:packet-receiver /usr/local/bin/mrecv/metrics_receiver.sh
sudo chown root:packet-receiver /usr/local/bin/mrecv/inject_scapy.py
sudo chmod 754 /usr/local/bin/mrecv/metrics_receiver.sh
sudo chmod 754 /usr/local/bin/mrecv/inject_scapy.py
```

Two systemd services will need to be created, one for each interface we want to monitor. Create two services, with the service spec highlighted down bellow.
```sh
sudo vim /etc/systemd/system/metrics_tap0_receiver.service
sudo cp /etc/systemd/system/metrics_tap0_receiver.service /etc/systemd/system/metrics_tap1_receiver.service
```

```sh
[Unit]
Description=Packet Receiver and TAP Injector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
User=packet-receiver
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
ExecStart=/usr/local/bin/mrecv/metrics_receiver.sh
ExecStartPre=/bin/test -f /usr/local/bin/mrecv/venv/bin/python
ExecStartPre=/usr/local/bin/mrecv/venv/bin/python -c "import scapy"
Environment="TAP_DEV="
Environment="LISTEN_PORT="
Environment="VENV_PY_PATH=/usr/local/bin/mrecv/venv/bin/python"
Environment="INJECT_SCRIPT=/usr/local/bin/mrecv/inject_scapy.py"
Environment="RETRY_INTERVAL=10"

[Install]
WantedBy=multi-user.target

```

Change the services environment variables to wire each of the services to a given tap interface and listening port (tap0 listens on 9998 and tap1 on 9999).
```sh
# tap0
sudo sed -i 's/Environment="TAP_DEV=".*/Environment="TAP_DEV=tap0"/' /etc/systemd/system/metrics_tap0_receiver.service
sudo sed -i 's/Environment="LISTEN_PORT=".*/Environment="LISTEN_PORT=9998"/' /etc/systemd/system/metrics_tap0_receiver.service
# tap1
sudo sed -i 's/Environment="TAP_DEV=".*/Environment="TAP_DEV=tap1"/' /etc/systemd/system/metrics_tap1_receiver.service
sudo sed -i 's/Environment="LISTEN_PORT=".*/Environment="LISTEN_PORT=9999"/' /etc/systemd/system/metrics_tap1_receiver.service
```

Reload systemd so it picks up the new service specs.
```sh
sudo systemctl daemon-reload
```

Enable the services so they start on boot
```sh
sudo systemctl enable metrics_tap0_receiver.service
sudo systemctl enable metrics_tap1_receiver.service
```

Start the services now
```sh
sudo systemctl start metrics_tap0_receiver.service
sudo systemctl start metrics_tap1_receiver.service
```

Verify they are running
```sh
sudo systemctl status metrics_tap0_receiver.service
sudo systemctl status metrics_tap1_receiver.service
```

Watch the logs. Should be waiting listening on the given port.
```sh
journalctl -u metrics_tap0_receiver.service -f
journalctl -u metrics_tap1_receiver.service -f
```

