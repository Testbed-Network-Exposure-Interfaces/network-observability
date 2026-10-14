#!/usr/bin/env python3
import sys
import struct
import os

# Open TAP device
tap = open('/dev/net/tun', 'r+b', buffering=0)

import fcntl
TUNSETIFF = 0x400454ca
IFF_TAP   = 0x0002
IFF_NO_PI = 0x1000

ifr = struct.pack('16sH', b'tap1', IFF_TAP | IFF_NO_PI)
fcntl.ioctl(tap, TUNSETIFF, ifr)

# Parse pcap from stdin and write frames to TAP
def read_pcap_packets(stream):
    # Global header
    magic = stream.read(4)
    if magic == b'\xd4\xc3\xb2\xa1':
        endian = '<'
    else:
        endian = '>'
    stream.read(20)  # rest of global header

    while True:
        rec_hdr = stream.read(16)
        if len(rec_hdr) < 16:
            break
        ts_sec, ts_usec, incl_len, orig_len = struct.unpack(endian + 'IIII', rec_hdr)
        data = stream.read(incl_len)
        if len(data) < incl_len:
            break
        yield data

stdin = open(sys.stdin.fileno(), 'rb', buffering=0)
for packet in read_pcap_packets(stdin):
    tap.write(packet)