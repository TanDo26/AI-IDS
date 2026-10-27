"""
Building frames and writing pcap / pcapng files: the tests' captures and the synthetic benchmark
(scripts/make_test_capture.py). Checksums are left at zero; neither extractor reads them.
"""

import socket
import struct

ETH_SRC, ETH_DST = bytes.fromhex("020000000001"), bytes.fromhex("020000000002")


def ip_packet(src: str, dst: str, proto: int, l4: bytes, *, ident=0, fragment=0, more_fragments=False, ttl=64,
              options=b"") -> bytes:
    """An IPv4 packet; `fragment` is the offset in 8-byte units."""
    ihl = 5 + len(options) // 4
    flags_frag = (0x2000 if more_fragments else 0) | fragment
    header = struct.pack("!BBHHHBBH4s4s", 0x40 | ihl, 0, ihl * 4 + len(l4), ident, flags_frag, ttl, proto, 0,
                         socket.inet_aton(src), socket.inet_aton(dst))
    return header + options + l4


def tcp_segment(sport, dport, flags, payload=b"", *, seq=0, ack=0, window=64240, options=b"") -> bytes:
    doff = 5 + len(options) // 4
    return struct.pack("!HHIIBBHHH", sport, dport, seq, ack, doff << 4, flags, window, 0, 0) + options + payload


def udp_datagram(sport, dport, payload=b"") -> bytes:
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def icmp_message(icmp_type, code, payload=b"\0\0\0\0") -> bytes:
    return struct.pack("!BBH", icmp_type, code, 0) + payload


def ethernet(packet: bytes, ethertype=0x0800, *, vlan=None, pad=True) -> bytes:
    """An Ethernet II frame, padded to the 60-byte minimum as a NIC would (the tools must ignore that)."""
    tag = struct.pack("!HH", 0x8100, vlan) if vlan is not None else b""
    frame = ETH_DST + ETH_SRC + tag + struct.pack("!H", ethertype) + packet
    return frame + b"\0" * (60 - len(frame)) if pad and len(frame) < 60 else frame


def tcp_frame(src, dst, sport, dport, flags, payload=b"", **fields) -> bytes:
    """`fields`: tcp_segment's keywords, plus ip_packet's ident and ttl."""
    ip_fields = {k: fields.pop(k) for k in ("ident", "ttl") if k in fields}
    return ethernet(ip_packet(src, dst, 6, tcp_segment(sport, dport, flags, payload, **fields), **ip_fields))


def udp_frame(src, dst, sport, dport, payload=b"") -> bytes:
    return ethernet(ip_packet(src, dst, 17, udp_datagram(sport, dport, payload)))


def icmp_frame(src, dst, icmp_type, code, payload=b"\0\0\0\0") -> bytes:
    return ethernet(ip_packet(src, dst, 1, icmp_message(icmp_type, code, payload)))


class PcapWriter:
    """Classic pcap, microsecond (or nanosecond) timestamps."""

    def __init__(self, f, linktype=1, *, nanos=False, snaplen=262144):
        self.f, self.nanos = f, nanos
        magic = 0xA1B23C4D if nanos else 0xA1B2C3D4
        f.write(struct.pack("<IHHiIII", magic, 2, 4, 0, 0, snaplen, linktype))

    def write(self, ts_us: int, frame: bytes, wirelen=None):
        sec, us = divmod(ts_us, 1_000_000)
        self.f.write(struct.pack("<IIII", sec, us * 1000 if self.nanos else us, len(frame), wirelen or len(frame)))
        self.f.write(frame)


class PcapngWriter:
    """pcapng with one interface; tsresol is the power of ten per second (6 = µs, 9 = ns)."""

    def __init__(self, f, linktype=1, *, tsresol=6):
        self.f, self.per_second = f, 10 ** tsresol
        self._block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
        options = struct.pack("<HHB3x", 9, 1, tsresol) + struct.pack("<HH", 0, 0)
        self._block(1, struct.pack("<HHI", linktype, 0, 262144) + options)

    def _block(self, block_type, body):
        body += b"\0" * (-len(body) % 4)
        length = 12 + len(body)
        self.f.write(struct.pack("<II", block_type, length) + body + struct.pack("<I", length))

    def write(self, ts_us: int, frame: bytes, wirelen=None):
        units = ts_us * self.per_second // 1_000_000
        self._block(6, struct.pack("<IIIII", 0, units >> 32, units & 0xFFFFFFFF, len(frame), wirelen or len(frame)) + frame)
