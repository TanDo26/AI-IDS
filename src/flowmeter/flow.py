"""
One bidirectional flow: its accumulators and feature values (port of BasicFlow at 13a0615).

The port is literal, quirks included, because the models were trained on the reference tool's output:
- A packet is forward when its source IP equals the flow's source IP (ports aren't compared).
- The subflow test `ts - last / 1e6 > 1.0` has misplaced brackets in the reference, so with real
  timestamps every packet starts a subflow: Subflow Fwd Packets = Total Fwd Packets // packets.
- Init Bwd Win Bytes is overwritten by every backward packet after the first one.
- FIN and RST counts per direction, and Fwd Act Data Packets, skip a flow's first packet.
- Flow IAT values are NaN for a one-packet flow; rates are inf (or NaN) for a zero-duration flow.
"""

import math
import socket
from datetime import datetime, timedelta, timezone

from .packet import ACK, CWR, ECE, FIN, PSH, RST, SYN, URG
from .stats import Stat

NAN = float("nan")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# TCP teardown states (TcpFlowState); None before any FIN or RST
FIRST_FIN, SECOND_FIN, READY_FOR_TERMINATION = 1, 2, 3


def _rate(count, duration_us):
    """count / seconds with Java's double division: x / 0.0 is inf, or NaN for 0 / 0.0."""
    seconds = duration_us / 1000000
    if seconds == 0:
        return NAN if count == 0 else math.inf
    return count / seconds


def java_timestamp(us: int) -> str:
    """The reference's Timestamp: UTC, ISO-8601 with ' ' for 'T', fraction in 0/3/6 digits (Instant.toString)."""
    moment = EPOCH + timedelta(microseconds=us)
    text = moment.strftime("%Y-%m-%d %H:%M:%S")
    micros = moment.microsecond
    if micros == 0:
        return text
    if micros % 1000 == 0:
        return f"{text}.{micros // 1000:03d}"
    return f"{text}.{micros:06d}"


class Flow:
    __slots__ = (
        "key", "src", "dst", "sport", "dport", "protocol", "icmp_code", "icmp_type", "activity_timeout",
        "start", "last_seen", "start_active", "end_active", "fwd_last", "bwd_last",
        "fwd_len", "bwd_len", "lengths", "flow_iat", "fwd_iat", "bwd_iat", "active", "idle",
        "fwd_bytes", "bwd_bytes", "fwd_header", "bwd_header", "flag_counts",
        "fwd_psh", "bwd_psh", "fwd_urg", "bwd_urg", "fwd_fin", "bwd_fin", "fwd_rst", "bwd_rst",
        "act_data_fwd", "min_seg_fwd", "init_win_fwd", "init_win_bwd",
        "sf_last", "sf_count",
        "fb_duration", "fb_packets", "fb_size", "fb_states", "fb_count_helper", "fb_start_helper",
        "fb_size_helper", "fb_last_ts",
        "bb_duration", "bb_packets", "bb_size", "bb_states", "bb_count_helper", "bb_start_helper",
        "bb_size_helper", "bb_last_ts",
        "cumulative", "tcp_state",
    )

    def __init__(self, packet, key, activity_timeout, src=None, dst=None, sport=0, dport=0):
        """`key` is the flow-table key, whose orientation is the Flow ID. The direction comes from the
        packet unless given: a TCP connection split by the timeout keeps its first piece's direction."""
        self.key = key
        if src is None:
            src, dst, sport, dport = packet.src, packet.dst, packet.sport, packet.dport
        self.src, self.dst, self.sport, self.dport = src, dst, sport, dport
        self.activity_timeout = activity_timeout
        self.fwd_len, self.bwd_len, self.lengths = Stat(), Stat(), Stat()
        self.flow_iat, self.fwd_iat, self.bwd_iat = Stat(), Stat(), Stat()
        self.active, self.idle = Stat(), Stat()
        self.fwd_bytes = self.bwd_bytes = self.fwd_header = self.bwd_header = 0
        self.flag_counts = [0] * 8                       # FIN SYN RST PSH ACK URG CWR ECE
        self.fwd_psh = self.bwd_psh = self.fwd_urg = self.bwd_urg = 0
        self.fwd_fin = self.bwd_fin = self.fwd_rst = self.bwd_rst = 0
        self.act_data_fwd = self.min_seg_fwd = self.init_win_fwd = self.init_win_bwd = 0
        self.fwd_last = self.bwd_last = 0
        self.sf_last, self.sf_count = -1, 0
        self.fb_duration = self.fb_packets = self.fb_size = self.fb_states = 0
        self.fb_count_helper = self.fb_start_helper = self.fb_size_helper = self.fb_last_ts = 0
        self.bb_duration = self.bb_packets = self.bb_size = self.bb_states = 0
        self.bb_count_helper = self.bb_start_helper = self.bb_size_helper = self.bb_last_ts = 0
        self.cumulative = 0                              # Total TCP Flow Time, set by the generator
        self.tcp_state = None
        self._first_packet(packet)

    @property
    def packets(self) -> int:
        return self.fwd_len.n + self.bwd_len.n

    # ── updates ──

    def _first_packet(self, p):
        self._update_bulk(p)
        self._check_flags(p.flags)
        ts = p.ts
        self.end_active = self.start = self.last_seen = self.start_active = ts
        self._detect_subflows(ts)
        payload = p.payload
        self.lengths.add(payload)
        flags = p.flags
        if p.src == self.src:
            self.min_seg_fwd = p.header
            self.init_win_fwd = p.window
            self.fwd_len.add(payload)
            self.fwd_header = p.header
            self.fwd_last = ts
            self.fwd_bytes += payload
            if flags & PSH:
                self.fwd_psh += 1
            if flags & URG:
                self.fwd_urg += 1
        else:
            self.init_win_bwd = p.window
            self.bwd_len.add(payload)
            self.bwd_header = p.header
            self.bwd_last = ts
            self.bwd_bytes += payload
            if flags & PSH:
                self.bwd_psh += 1
            if flags & URG:
                self.bwd_urg += 1
        self.protocol = p.proto
        self.icmp_code = p.icmp_code
        self.icmp_type = p.icmp_type

    def add(self, p):
        """addPacket: every packet after the first."""
        self._update_bulk(p)
        ts = p.ts
        self._detect_subflows(ts)
        flags = p.flags
        if flags:
            self._check_flags(flags)
        payload = p.payload
        self.lengths.add(payload)
        if p.src == self.src:
            if payload >= 1:
                self.act_data_fwd += 1
            self.fwd_len.add(payload)
            self.fwd_header += p.header
            self.fwd_bytes += payload
            if self.fwd_len.n > 1:
                self.fwd_iat.add(ts - self.fwd_last)
            self.fwd_last = ts
            if p.header < self.min_seg_fwd:
                self.min_seg_fwd = p.header
            if flags:
                if flags & PSH:
                    self.fwd_psh += 1
                if flags & URG:
                    self.fwd_urg += 1
                if flags & FIN:
                    self.fwd_fin += 1
                if flags & RST:
                    self.fwd_rst += 1
        else:
            self.bwd_len.add(payload)
            self.init_win_bwd = p.window
            self.bwd_header += p.header
            self.bwd_bytes += payload
            if self.bwd_len.n > 1:
                self.bwd_iat.add(ts - self.bwd_last)
            self.bwd_last = ts
            if flags:
                if flags & PSH:
                    self.bwd_psh += 1
                if flags & URG:
                    self.bwd_urg += 1
                if flags & FIN:
                    self.bwd_fin += 1
                if flags & RST:
                    self.bwd_rst += 1
        self.flow_iat.add(ts - self.last_seen)
        self.last_seen = ts

    def update_active_idle(self, now, threshold):
        if now - self.end_active > threshold:
            if self.end_active - self.start_active > 0:
                self.active.add(self.end_active - self.start_active)
            self.idle.add(now - self.end_active)
            self.start_active = self.end_active = now
        else:
            self.end_active = now

    def _check_flags(self, flags):
        counts = self.flag_counts
        if flags & FIN:
            counts[0] += 1
        if flags & SYN:
            counts[1] += 1
        if flags & RST:
            counts[2] += 1
        if flags & PSH:
            counts[3] += 1
        if flags & ACK:
            counts[4] += 1
        if flags & URG:
            counts[5] += 1
        if flags & CWR:
            counts[6] += 1
        if flags & ECE:
            counts[7] += 1

    def _detect_subflows(self, ts):
        if self.sf_last == -1:
            self.sf_last = ts
        if ts - self.sf_last / 1000000.0 > 1.0:          # sic: (ts - last) / 1e6 was meant
            self.sf_count += 1
            self.update_active_idle(ts, self.activity_timeout)
        self.sf_last = ts

    def _update_bulk(self, p):
        size = p.payload
        if p.src == self.src:
            if self.bb_last_ts > self.fb_start_helper:
                self.fb_start_helper = 0
            if size <= 0:
                return
            ts = p.ts
            if self.fb_start_helper == 0:
                self.fb_start_helper = self.fb_last_ts = ts
                self.fb_count_helper, self.fb_size_helper = 1, size
            elif (ts - self.fb_last_ts) / 1000000.0 > 1.0:
                self.fb_start_helper = self.fb_last_ts = ts
                self.fb_count_helper, self.fb_size_helper = 1, size
            else:
                self.fb_count_helper += 1
                self.fb_size_helper += size
                if self.fb_count_helper == 4:
                    self.fb_states += 1
                    self.fb_packets += self.fb_count_helper
                    self.fb_size += self.fb_size_helper
                    self.fb_duration += ts - self.fb_start_helper
                elif self.fb_count_helper > 4:
                    self.fb_packets += 1
                    self.fb_size += size
                    self.fb_duration += ts - self.fb_last_ts
                self.fb_last_ts = ts
        else:
            if self.fb_last_ts > self.bb_start_helper:
                self.bb_start_helper = 0
            if size <= 0:
                return
            ts = p.ts
            if self.bb_start_helper == 0:
                self.bb_start_helper = self.bb_last_ts = ts
                self.bb_count_helper, self.bb_size_helper = 1, size
            elif (ts - self.bb_last_ts) / 1000000.0 > 1.0:
                self.bb_start_helper = self.bb_last_ts = ts
                self.bb_count_helper, self.bb_size_helper = 1, size
            else:
                self.bb_count_helper += 1
                self.bb_size_helper += size
                if self.bb_count_helper == 4:
                    self.bb_states += 1
                    self.bb_packets += self.bb_count_helper
                    self.bb_size += self.bb_size_helper
                    self.bb_duration += ts - self.bb_start_helper
                elif self.bb_count_helper > 4:
                    self.bb_packets += 1
                    self.bb_size += size
                    self.bb_duration += ts - self.bb_last_ts
                self.bb_last_ts = ts

    # ── output ──

    def metadata(self) -> tuple:
        src, dst, sport, dport, proto = self.key
        flow_id = f"{socket.inet_ntoa(src)}-{socket.inet_ntoa(dst)}-{sport}-{dport}-{proto}"
        return (flow_id, socket.inet_ntoa(self.src), self.sport, socket.inet_ntoa(self.dst), self.dport,
                java_timestamp(self.start))

    def features(self) -> tuple:
        """The 82 values in schema.FEATURES order (dumpFlowBasedFeaturesEx)."""
        duration = self.last_seen - self.start
        fwd, bwd, lengths = self.fwd_len, self.bwd_len, self.lengths
        n_fwd, n_bwd = fwd.n, bwd.n
        packets = n_fwd + n_bwd
        flow_iat, fwd_iat, bwd_iat, active, idle = self.flow_iat, self.fwd_iat, self.bwd_iat, self.active, self.idle
        sf = self.sf_count
        return (
            self.protocol, duration, n_fwd, n_bwd, fwd.total, bwd.total,
            *((fwd.hi, fwd.lo, fwd.mean, fwd.std) if n_fwd else (0, 0, 0, 0)),
            *((bwd.hi, bwd.lo, bwd.mean, bwd.std) if n_bwd else (0, 0, 0, 0)),
            _rate(self.fwd_bytes + self.bwd_bytes, duration), _rate(packets, duration),
            flow_iat.mean, flow_iat.std, flow_iat.hi, flow_iat.lo,
            *((fwd_iat.total, fwd_iat.mean, fwd_iat.std, fwd_iat.hi, fwd_iat.lo) if n_fwd > 1 else (0,) * 5),
            *((bwd_iat.total, bwd_iat.mean, bwd_iat.std, bwd_iat.hi, bwd_iat.lo) if n_bwd > 1 else (0,) * 5),
            self.fwd_psh, self.bwd_psh, self.fwd_urg, self.bwd_urg, self.fwd_rst, self.bwd_rst,
            self.fwd_header, self.bwd_header,
            n_fwd / (duration / 1000000) if duration > 0 else 0,
            n_bwd / (duration / 1000000) if duration > 0 else 0,
            lengths.lo, lengths.hi, lengths.mean, lengths.std, lengths.variance,
            *self.flag_counts,
            n_bwd / n_fwd if n_fwd else 0,
            lengths.total / packets,
            fwd.total / n_fwd if n_fwd else 0,
            bwd.total / n_bwd if n_bwd else 0,
            self.fb_size // self.fb_states if self.fb_states else 0,
            self.fb_packets // self.fb_states if self.fb_states else 0,
            int(self.fb_size / (self.fb_duration / 1000000)) if self.fb_duration else 0,
            self.bb_size // self.bb_states if self.bb_states else 0,
            self.bb_packets // self.bb_states if self.bb_states else 0,
            int(self.bb_size / (self.bb_duration / 1000000)) if self.bb_duration else 0,
            *((n_fwd // sf, self.fwd_bytes // sf, n_bwd // sf, self.bwd_bytes // sf) if sf > 0 else (0, 0, 0, 0)),
            self.init_win_fwd, self.init_win_bwd, self.act_data_fwd, self.min_seg_fwd,
            *((active.mean, active.std, active.hi, active.lo) if active.n else (0, 0, 0, 0)),
            *((idle.mean, idle.std, idle.hi, idle.lo) if idle.n else (0, 0, 0, 0)),
            self.icmp_code, self.icmp_type, self.cumulative,
        )
