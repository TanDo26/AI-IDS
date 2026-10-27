"""
Packets from a pcap or pcapng file (port of PacketReader at 13a0615, with jnetpcap's header rules).

Only IPv4 is read, like the reference's command-line tool (it calls PacketReader with IPv6 off):
- ICMP, TCP and UDP get their ports, flags, window and ICMP code/type. Any other protocol, a
  non-first fragment, or a header cut short becomes protocol 0 with ports 0, as in the reference.
- Payload = what follows the TCP/UDP header up to the IPv4 total length, so Ethernet padding isn't
  counted (jnetpcap trims it the same way). ICMP and protocol 0 packets have payload and header 0.
- Timestamps are microseconds; nanosecond captures are truncated, as libpcap does.

Frames that aren't IPv4 (ARP, IPv6, ...) are skipped and counted.
Differences from the reference, all in frames it doesn't read correctly:
- It reads some ARP frames as IPv4 from the frame's first byte, which yields a protocol-0 flow
  between 8.6.0.1 and 8.0.6.4 (the ARP header's bytes); others it discards. Not replicated.
- It parses every capture as Ethernet; here Linux cooked (SLL, SLL2), raw IP and loopback captures
  are read too, with the same results as the same packets over Ethernet.
- It counts the padding of short frames behind a VLAN tag as payload (jnetpcap trims it only right
  after an Ethernet header); here the IPv4 length applies there too.
"""

import mmap
import os
import struct
from collections import Counter
from collections.abc import Callable, Iterator

from .packet import ICMP, TCP, UDP, Packet

PCAP_MAGICS = {   # first 4 bytes -> (byte order, nanosecond timestamps)
    b"\xd4\xc3\xb2\xa1": ("<", False), b"\xa1\xb2\xc3\xd4": (">", False),
    b"\x4d\x3c\xb2\xa1": ("<", True), b"\xa1\xb2\x3c\x4d": (">", True),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"

ETHERNET, RAW, RAW_BSD, RAW_OPENBSD, IPV4 = 1, 101, 12, 14, 228
LINUX_SLL, LINUX_SLL2, NULL, LOOP = 113, 276, 0, 108
LINK_TYPES = {ETHERNET, RAW, RAW_BSD, RAW_OPENBSD, IPV4, LINUX_SLL, LINUX_SLL2, NULL, LOOP}
VLAN_TYPES = {0x8100, 0x88A8, 0x9100}

PROGRESS_STEP = 0.01               # share of the file between progress reports


class CaptureError(ValueError):
    """The file can't be read as a capture; the message is shown to the user."""


def _ipv4_offset(buf, start, end, linktype, stats) -> int:
    """Where the IPv4 header starts in this frame, or -1 (counted in stats by reason)."""
    if linktype == ETHERNET:
        off = start + 14
        if off > end:
            stats["malformed"] += 1
            return -1
        ethertype = buf[off - 2] << 8 | buf[off - 1]
        while ethertype in VLAN_TYPES and off + 4 <= end:
            ethertype = buf[off + 2] << 8 | buf[off + 3]
            off += 4
    elif linktype == LINUX_SLL:
        off = start + 16
        ethertype = buf[off - 2] << 8 | buf[off - 1] if off <= end else -1
    elif linktype == LINUX_SLL2:
        off = start + 20
        ethertype = buf[start] << 8 | buf[start + 1] if off <= end else -1
    elif linktype in (NULL, LOOP):
        off = start + 4
        family = bytes(buf[start:off]) if off <= end else b""
        ethertype = 0x0800 if family in (b"\x02\x00\x00\x00", b"\x00\x00\x00\x02") else 0
    else:  # raw IP
        off = start
        ethertype = 0x0800 if off < end and buf[off] >> 4 == 4 else (0x86DD if off < end and buf[off] >> 4 == 6 else 0)
    if ethertype == 0x0800:
        return off
    if ethertype == -1:
        stats["malformed"] += 1
    elif ethertype == 0x86DD:
        stats["ipv6"] += 1
    else:
        stats["not_ip"] += 1
    return -1


_IPV4 = struct.Struct("!BxHxxHxB2x4s4s")      # version/IHL, total length, flags/fragment, protocol, src, dst
_TCP = struct.Struct("!HH8xBBH")               # ports, data offset, flags, window
_PORTS = struct.Struct("!HH")


def _parse(buf, start, caplen, wirelen, linktype, ts, stats) -> Packet | None:
    end = start + (caplen if caplen < wirelen else wirelen)
    if linktype == ETHERNET and end - start >= 14 and buf[start + 12] == 8 and buf[start + 13] == 0:
        off = start + 14                        # the common case: untagged IPv4 over Ethernet
    else:
        off = _ipv4_offset(buf, start, end, linktype, stats)
        if off < 0:
            return None
    if end - off < 20:
        stats["malformed"] += 1
        return None
    version_ihl, total_length, fragment, proto, src, dst = _IPV4.unpack_from(buf, off)
    if version_ihl >> 4 != 4 or version_ihl & 0x0F < 5:
        stats["malformed"] += 1
        return None
    if off + total_length < end:              # Ethernet padding / trailer
        end = off + total_length
    l4 = off + (version_ihl & 0x0F) * 4
    remain = end - l4
    if not fragment & 0x1FFF:
        if proto == TCP and remain >= 20:
            sport, dport, data_offset, flags, window = _TCP.unpack_from(buf, l4)
            header = (data_offset >> 4) * 4
            if header > remain:
                header = remain
            return Packet(ts, src, dst, sport, dport, TCP, remain - header, header, window, flags)
        if proto == UDP and remain >= 8:
            sport, dport = _PORTS.unpack_from(buf, l4)
            return Packet(ts, src, dst, sport, dport, UDP, remain - 8, 8)
        if proto == ICMP and remain >= 4:
            return Packet(ts, src, dst, proto=ICMP, icmp_type=buf[l4], icmp_code=buf[l4 + 1])
    return Packet(ts, src, dst)                 # protocol 0, as the reference


def _pcap_records(buf, size) -> Iterator[tuple]:
    order, nanos = PCAP_MAGICS[bytes(buf[:4])]
    if size < 24:
        raise CaptureError("The capture is truncated: its file header is incomplete")
    linktype = struct.unpack_from(order + "I", buf, 20)[0] & 0x0FFFFFFF
    record = struct.Struct(order + "IIII")
    pos = 24
    while pos + 16 <= size:
        sec, frac, caplen, wirelen = record.unpack_from(buf, pos)
        pos += 16
        if pos + caplen > size:
            break                                   # last packet cut off (capture still being written)
        yield sec * 1_000_000 + (frac // 1000 if nanos else frac), linktype, pos, caplen, wirelen
        pos += caplen


def _pcapng_records(buf, size) -> Iterator[tuple]:
    order, interfaces, pos = "<", [], 0
    while pos + 12 <= size:
        block_type = struct.unpack_from(order + "I", buf, pos)[0]
        if block_type == 0x0A0D0D0A:                  # section header: byte order, new interface list
            magic = bytes(buf[pos + 8:pos + 12])
            order = "<" if magic == b"\x4d\x3c\x2b\x1a" else ">" if magic == b"\x1a\x2b\x3c\x4d" else None
            if order is None:
                raise CaptureError("Not a valid pcapng file: unknown byte-order magic")
            interfaces = []
        length = struct.unpack_from(order + "I", buf, pos + 4)[0]
        if length < 12 or length % 4 or pos + length > size:
            break                                       # truncated or damaged: keep what was read
        if block_type == 1:                             # interface description
            linktype = struct.unpack_from(order + "H", buf, pos + 8)[0]
            per_second, offset = 1_000_000, 0
            opt, opt_end = pos + 16, pos + length - 4
            while opt + 4 <= opt_end:
                code, opt_len = struct.unpack_from(order + "HH", buf, opt)
                if code == 0:
                    break
                if code == 9 and opt_len >= 1:          # if_tsresol
                    resol = buf[opt + 4]
                    per_second = 2 ** (resol & 0x7F) if resol & 0x80 else 10 ** resol
                elif code == 14 and opt_len >= 8:       # if_tsoffset, seconds
                    offset = struct.unpack_from(order + "q", buf, opt + 4)[0]
                opt += 4 + (opt_len + 3) // 4 * 4
            interfaces.append((linktype, per_second, offset))
        elif block_type in (6, 2):                      # enhanced / obsolete packet block
            if block_type == 6:
                iface, high, low, caplen, wirelen = struct.unpack_from(order + "IIIII", buf, pos + 8)
            else:
                iface, _drops, high, low, caplen, wirelen = struct.unpack_from(order + "HHIIII", buf, pos + 8)
            if iface < len(interfaces) and 28 + caplen <= length - 4:
                linktype, per_second, offset = interfaces[iface]
                units = high << 32 | low
                ts = units * 1_000_000 // per_second + offset * 1_000_000
                yield ts, linktype, pos + 28, caplen, wirelen
        pos += length


def read_packets(path, stats: Counter | None = None,
                 progress: Callable[[float], None] | None = None) -> Iterator[Packet]:
    """Every usable IPv4 packet of the capture, in file order. `stats` counts what was read and skipped
    (packets, ipv4, ipv6, not_ip, malformed, unsupported_link); `progress` gets the fraction read."""
    stats = Counter() if stats is None else stats
    size = os.path.getsize(path)
    if size < 4:
        raise CaptureError("The file is too short to be a capture")
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as buf:
        head = bytes(buf[:4])
        if head in PCAP_MAGICS:
            records = _pcap_records(buf, size)
        elif head == PCAPNG_MAGIC:
            records = _pcapng_records(buf, size)
        else:
            raise CaptureError("Not a pcap or pcapng capture")
        count = used = 0
        step = next_report = max(int(size * PROGRESS_STEP), 1)
        try:
            for ts, linktype, start, caplen, wirelen in records:
                count += 1
                if progress is not None and start >= next_report:
                    progress(start / size)
                    next_report = start + step
                if linktype not in LINK_TYPES:
                    stats["unsupported_link"] += 1
                    continue
                packet = _parse(buf, start, caplen, wirelen, linktype, ts, stats)
                if packet is not None:
                    used += 1
                    yield packet
        finally:
            stats["packets"] += count
            stats["ipv4"] += used
