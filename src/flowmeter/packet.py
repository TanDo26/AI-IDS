"""One packet, reduced to what flows need (port of BasicPacketInfo)."""

# TCP flag bits
FIN, SYN, RST, PSH, ACK, URG, ECE, CWR = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80

# Protocol numbers the reference tool knows; every other IPv4 protocol becomes 0
ICMP, TCP, UDP, OTHER = 1, 6, 17, 0


class Packet:
    """IPv4 addresses are 4-byte strings. Sizes are those of the TCP/UDP header and its payload
    (0 for ICMP and other protocols, as in the reference); timestamps are in microseconds."""

    __slots__ = ("ts", "src", "dst", "sport", "dport", "proto", "payload", "header", "window", "flags",
                 "icmp_code", "icmp_type")

    def __init__(self, ts, src, dst, sport=0, dport=0, proto=OTHER, payload=0, header=0, window=0, flags=0,
                 icmp_code=-1, icmp_type=-1):
        self.ts = ts
        self.src = src
        self.dst = dst
        self.sport = sport
        self.dport = dport
        self.proto = proto
        self.payload = payload
        self.header = header
        self.window = window
        self.flags = flags
        self.icmp_code = icmp_code
        self.icmp_type = icmp_type
