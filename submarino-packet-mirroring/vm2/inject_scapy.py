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
