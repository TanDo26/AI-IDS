"""
Write a synthetic capture for the flow extractor: its parity test against the reference tool and its
speed benchmark (README "Flow extractor").

Sessions start at random and overlap; each picks one kind of traffic that exercises a rule of the
flow meter: HTTP-like TCP with bulk transfers and both close orders, RST closes, connections idle past
the activity timeout or longer than the 120 s flow timeout, port scans (one-packet flows), a 4-tuple
reused after a close, DNS-like UDP, long UDP streams that change direction, ICMP echo / unreachable /
time exceeded, fragmented datagrams, other IP protocols (GRE, IGMP, ESP), URG/ECE/CWR flags and
same-address traffic; VLAN tags with --vlan. Small frames are padded to 60 bytes, as on a wire.

    python scripts/make_test_capture.py --packets 20000 --out capture.pcap
    python scripts/make_test_capture.py --size-mb 100 --out big.pcap          # the benchmark
    python scripts/make_test_capture.py --packets 2000 --non-ip --out arp.pcap  # adds ARP and IPv6 frames
"""
import sys
import heapq
import random
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.flowmeter.pcapwriter import (PcapngWriter, PcapWriter, ethernet, icmp_message, ip_packet,
                                      tcp_segment, udp_datagram)

FIN, SYN, RST, PSH, ACK, URG, ECE, CWR = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80
START_US = 1_499_256_000_000_000                     # 2017-07-05 12:00 UTC
MSS_OPTIONS = bytes.fromhex("020405b4 0402 080a 0000000000000000 01 030307".replace(" ", ""))
TS_OPTIONS = bytes.fromhex("0101080a0000000000000000")


class Session:
    """Yields (offset µs from the session start, frame); offsets never decrease."""

    def __init__(self, rng: random.Random, n: int):
        self.rng, self.n = rng, n
        self.client = f"192.168.{rng.randint(10, 13)}.{rng.randint(2, 250)}"
        self.server = f"{rng.choice(['10.0.0', '172.16.5', '205.174.165'])}.{rng.randint(2, 250)}"
        self.cport, self.sport = rng.randint(1024, 65535), rng.choice([21, 22, 25, 53, 80, 443, 445, 3389, 8080])

    def gap(self, mean_us):
        return max(1, int(self.rng.expovariate(1 / mean_us)))

    def tcp(self, src, dst, sport, dport, flags, payload=0, *, vlan=None, options=b"", window=None):
        window = window if window is not None else self.rng.choice([229, 502, 8192, 29200, 64240, 65535])
        segment = tcp_segment(sport, dport, flags, b"\0" * payload, window=window, options=options)
        return ethernet(ip_packet(src, dst, 6, segment), vlan=vlan)

    def c2s(self, flags, payload=0, **kw):
        return self.tcp(self.client, self.server, self.cport, self.sport, flags, payload, **kw)

    def s2c(self, flags, payload=0, **kw):
        return self.tcp(self.server, self.client, self.sport, self.cport, flags, payload, **kw)

    def handshake(self, t, **kw):
        yield t, self.c2s(SYN, options=MSS_OPTIONS, **kw)
        t += self.gap(400)
        yield t, self.s2c(SYN | ACK, options=MSS_OPTIONS[:8], **kw)
        t += self.gap(200)
        yield t, self.c2s(ACK, **kw)
        return

    def close(self, t, kind, **kw):
        rng = self.rng
        if kind == "rst":
            yield t, (self.c2s if rng.random() < 0.5 else self.s2c)(RST | ACK if rng.random() < 0.7 else RST, **kw)
        elif kind == "fin_client":
            yield t, self.c2s(FIN | ACK, **kw)
            t += self.gap(300)
            yield t, self.s2c(FIN | ACK, **kw)
            t += self.gap(200)
            yield t, self.c2s(ACK, **kw)
        elif kind == "fin_server":
            yield t, self.s2c(FIN | ACK, **kw)
            t += self.gap(300)
            yield t, self.c2s(ACK, **kw)
            t += self.gap(5000)
            yield t, self.c2s(FIN | ACK, **kw)
            t += self.gap(200)
            yield t, self.s2c(ACK, **kw)
        # "open": no close at all

    def run(self):
        kind = self.rng.choices(KINDS, WEIGHTS)[0]
        yield from getattr(self, kind)()

    # ── kinds ──

    def web(self):
        rng, t = self.rng, 0
        kw = {"vlan": 10 if rng.random() < VLAN_SHARE else None}
        for t, frame in self.handshake(t, **kw):
            yield t, frame
        for _ in range(rng.choice([1, 1, 2, 3, 5])):
            t += self.gap(2000)
            yield t, self.c2s(PSH | ACK, rng.randint(80, 900), options=TS_OPTIONS if rng.random() < 0.3 else b"", **kw)
            t += self.gap(3000)
            yield t, self.s2c(ACK, **kw)
            for i in range(rng.choice([1, 2, 4, 6, 12, 30])):
                t += self.gap(rng.choice([80, 400, 1_500_000]))
                yield t, self.s2c((PSH | ACK) if i % 3 == 2 else ACK, rng.choice([1460, 1460, 600, 33]), **kw)
                if i % 2:
                    t += self.gap(100)
                    yield t, self.c2s(ACK, **kw)
            if rng.random() < 0.1:
                t += self.gap(100)
                yield t, self.c2s(URG | ACK | PSH, 1, **kw)
            if rng.random() < 0.05:
                t += self.gap(100)
                yield t, self.s2c(ECE | ACK, **kw)
                t += self.gap(100)
                yield t, self.c2s(CWR | ACK, 10, **kw)
        t += self.gap(20_000)
        yield from self.close(t, rng.choice(["fin_client", "fin_client", "fin_server", "rst", "open"]), **kw)

    def idle(self):
        """Keep-alive with pauses past the 5 s activity timeout; some outlast the 120 s flow timeout."""
        rng, t = self.rng, 0
        for t, frame in self.handshake(t):
            yield t, frame
        long = rng.random() < 0.5
        for _ in range(rng.randint(3, 12 if long else 5)):
            t += rng.choice([300_000, 6_000_000, 9_000_000, 40_000_000 if long else 2_000_000])
            yield t, self.c2s(PSH | ACK, rng.randint(1, 200))
            t += self.gap(500)
            yield t, self.s2c(PSH | ACK, rng.randint(1, 1460))
            t += self.gap(300)
            yield t, self.c2s(ACK)
        t += self.gap(1000)
        yield from self.close(t, rng.choice(["fin_client", "fin_server", "rst", "open"]))

    def scan(self):
        rng, t = self.rng, 0
        for _ in range(rng.randint(5, 60)):
            self.sport = rng.randint(1, 10000)
            yield t, self.c2s(SYN, window=1024)
            outcome = rng.random()
            if outcome < 0.6:
                yield t + self.gap(200), self.s2c(RST | ACK, window=0)
            elif outcome < 0.8:
                yield t + self.gap(200), self.s2c(SYN | ACK, options=MSS_OPTIONS[:4])
                yield t + 300 + self.gap(100), self.c2s(RST, window=0)
            t += self.gap(500)

    def reuse(self):
        """The same 4-tuple again after a close: a SYN after the teardown starts a new flow."""
        rng, t = self.rng, 0
        for _ in range(rng.randint(2, 4)):
            for t, frame in self.handshake(t):
                yield t, frame
            t += self.gap(1000)
            yield t, self.c2s(PSH | ACK, rng.randint(10, 300))
            t += self.gap(1000)
            yield t, self.s2c(PSH | ACK, rng.randint(10, 3000))
            t += self.gap(1000)
            for t, frame in self.close(t, rng.choice(["fin_client", "fin_server", "rst"])):
                yield t, frame
            t += self.gap(rng.choice([50_000, 3_000_000]))
            if rng.random() < 0.2:                       # a stray SYN-ACK hits the finished flow first
                yield t, self.s2c(SYN | ACK)
                t += self.gap(1000)

    def dns(self):
        rng, t = self.rng, 0
        resolver, self.sport = rng.choice(["8.8.8.8", "192.168.10.3"]), 53
        for _ in range(rng.choice([1, 1, 1, 2, 4])):
            yield t, ethernet(ip_packet(self.client, resolver, 17, udp_datagram(self.cport, 53, b"q" * rng.randint(17, 60))))
            if rng.random() < 0.9:
                t += self.gap(rng.choice([300, 30_000]))
                yield t, ethernet(ip_packet(resolver, self.client, 17, udp_datagram(53, self.cport, b"a" * rng.randint(30, 500))))
            t += self.gap(200_000)

    def stream(self):
        """Long UDP stream that outlasts the flow timeout and is sometimes picked up by the other side."""
        rng, t = self.rng, 0
        a, b, pa, pb = self.client, self.server, self.cport, rng.choice([123, 514, 5060, 1194])
        for _ in range(rng.randint(5, 25)):
            src, dst, sp, dp = (a, b, pa, pb) if rng.random() < 0.6 else (b, a, pb, pa)
            yield t, ethernet(ip_packet(src, dst, 17, udp_datagram(sp, dp, b"\0" * rng.randint(20, 1200))))
            t += rng.choice([self.gap(2000), 7_000_000, 30_000_000])

    def icmp(self):
        rng, t = self.rng, 0
        target = self.server
        for i in range(rng.randint(1, 6)):
            yield t, ethernet(ip_packet(self.client, target, 1, icmp_message(8, 0, b"\0" * 56)))
            if rng.random() < 0.8:
                yield t + self.gap(800), ethernet(ip_packet(target, self.client, 1, icmp_message(0, 0, b"\0" * 56)))
            t += self.gap(1_000_000)
        error = rng.choice([(3, 3), (3, 1), (11, 0), (11, 1), (5, 1)])
        quoted = ip_packet(self.client, target, 17, udp_datagram(self.cport, 33434, b"\0" * 12))[:28]
        for _ in range(rng.randint(1, 3)):
            yield t, ethernet(ip_packet(target, self.client, 1, icmp_message(*error, b"\0\0\0\0" + quoted)))
            t += self.gap(1000)
        yield t, ethernet(ip_packet(self.client, target, 1, icmp_message(13, 0, b"\0" * 16)))  # timestamp request

    def fragments(self):
        rng, t = self.rng, 0
        ident = rng.randint(1, 65535)
        data = udp_datagram(self.cport, 5004, b"\0" * rng.randint(3000, 6000))
        chunks = [data[i:i + 1480] for i in range(0, len(data), 1480)]
        for i, chunk in enumerate(chunks):
            yield t, ethernet(ip_packet(self.client, self.server, 17, chunk, ident=ident, fragment=i * 185,
                                        more_fragments=i < len(chunks) - 1))
            t += self.gap(50)
        yield t + self.gap(1000), ethernet(ip_packet(self.server, self.client, 17, udp_datagram(5004, self.cport, b"ok")))

    def other(self):
        rng, t = self.rng, 0
        proto = rng.choice([2, 47, 50, 89])
        for _ in range(rng.randint(2, 20)):
            src, dst = (self.client, self.server) if rng.random() < 0.7 else (self.server, self.client)
            yield t, ethernet(ip_packet(src, dst, proto, b"\0" * rng.randint(8, 400)))
            t += self.gap(rng.choice([10_000, 3_000_000]))

    def same_host(self):
        rng, t = self.rng, 0
        self.server = self.client
        for t, frame in self.handshake(t):
            yield t, frame
        for _ in range(rng.randint(1, 6)):
            t += self.gap(500)
            yield t, (self.c2s if rng.random() < 0.5 else self.s2c)(PSH | ACK, rng.randint(1, 500))
        yield from self.close(t + 100, "fin_client")

    def non_ip(self):
        rng, t = self.rng, 0
        for _ in range(rng.randint(1, 4)):
            arp = bytes.fromhex("0001080006040001") + bytes(6) + bytes([192, 168, 10, rng.randint(2, 250)]) + bytes(10)
            yield t, ethernet(arp, 0x0806)
            t += self.gap(10_000)
            ipv6 = bytes.fromhex("6000000000141140") + bytes(15) + b"\x01" + bytes(15) + b"\x02" + udp_datagram(546, 547, b"\0" * 12)
            yield t, ethernet(ipv6, 0x86DD)
            t += self.gap(10_000)


VLAN_SHARE = 0.0                                     # --vlan

KINDS = ["web", "idle", "scan", "reuse", "dns", "stream", "icmp", "fragments", "other", "same_host"]
WEIGHTS = [40, 6, 6, 5, 25, 3, 6, 2, 3, 2]


def packets(n_target, seed, non_ip, arrival_us):
    """(timestamp, frame) in time order: sessions merged on a heap as they start."""
    rng = random.Random(seed)
    heap, made, t, count = [], 0, START_US, 0
    while count < n_target:
        # start sessions up to the next packet's time
        while not heap or heap[0][0] >= t:
            session = Session(random.Random(rng.random()), made)
            if non_ip and made % 20 == 0:
                gen = session.non_ip()
            else:
                gen = session.run()
            first = next(gen, None)
            if first is not None:
                heapq.heappush(heap, (t + first[0], made, t, first[1], gen))
            made += 1
            t += max(1, int(rng.expovariate(1 / arrival_us)))
        ts, order, base, frame, gen = heapq.heappop(heap)
        yield ts, frame
        count += 1
        nxt = next(gen, None)
        if nxt is not None:
            heapq.heappush(heap, (base + nxt[0], order, base, nxt[1], gen))


def main(args):
    global VLAN_SHARE
    VLAN_SHARE = args.vlan
    n_target = 10 ** 12 if args.size_mb else args.packets     # with --size-mb, the file size decides
    writer_cls = PcapngWriter if args.out.suffix == ".pcapng" else PcapWriter
    written = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        writer = writer_cls(f)
        for ts, frame in packets(n_target, args.seed, args.non_ip, args.arrival_us):
            captured = frame[:args.snaplen] if args.snaplen else frame
            writer.write(ts, captured, len(frame))
            written += 1
            if args.size_mb and f.tell() >= args.size_mb * 1_000_000:
                break
    print(f"  {written:,} packets, {args.out.stat().st_size / 1e6:.1f} MB -> {args.out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write a synthetic capture for the flow extractor")
    parser.add_argument("--packets", type=int, default=20_000)
    parser.add_argument("--size-mb", type=float, help="stop at this file size instead (decimal MB)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--arrival-us", type=float, default=20_000, help="mean gap between session starts")
    parser.add_argument("--non-ip", action="store_true", help="add ARP and IPv6 frames")
    parser.add_argument("--vlan", type=float, default=0.0,
                        help="share of web sessions with a VLAN tag (padding behind a tag is where the "
                             "reference differs)")
    parser.add_argument("--snaplen", type=int, help="cut frames to this many bytes (truncated capture)")
    parser.add_argument("--out", type=Path, required=True, help=".pcap or .pcapng")
    main(parser.parse_args())
