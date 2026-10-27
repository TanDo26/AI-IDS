"""
Flow extractor (src/flowmeter): small captures built here, values worked out by hand from the reference
CICFlowMeter's rules. Its parity with the Java tool itself is checked by scripts/validate_flowmeter.py.
"""

import math
import statistics
import struct
from collections import Counter

import pandas as pd
import pytest

from src.flowmeter import CaptureError, FEATURES, extract_flows, generator, iter_flows
from src.flowmeter.__main__ import main as cli
from src.flowmeter.flow import java_timestamp
from src.flowmeter.pcapwriter import (PcapngWriter, PcapWriter, ethernet, icmp_message, ip_packet, tcp_segment,
                                      udp_datagram)
from src.flowmeter.stats import Stat

FIN, SYN, RST, PSH, ACK = 0x01, 0x02, 0x04, 0x08, 0x10
T0 = 1_499_256_000_000_000                  # 2017-07-05 12:00:00 UTC, in µs
C, S = "192.168.10.5", "10.0.0.9"           # client, server
SECOND = 1_000_000


def tcp(src, dst, sport, dport, flags, payload=0, window=8192, options=b""):
    return ip_packet(src, dst, 6, tcp_segment(sport, dport, flags, b"x" * payload, window=window, options=options))


def c2s(flags, payload=0, **kw):
    return tcp(C, S, 40000, 80, flags, payload, **kw)


def s2c(flags, payload=0, **kw):
    return tcp(S, C, 80, 40000, flags, payload, **kw)


def udp(src, dst, sport, dport, payload=0):
    return ip_packet(src, dst, 17, udp_datagram(sport, dport, b"u" * payload))


def icmp(src, dst, icmp_type, code):
    return ip_packet(src, dst, 1, icmp_message(icmp_type, code, b"\0" * 32))


def write(path, packets, *, writer=PcapWriter, linktype=1, frame=ethernet, **options):
    """packets: (µs after T0, IPv4 packet); `frame` wraps each packet for the link type."""
    with open(path, "wb") as f:
        w = writer(f, linktype, **options)
        for dt, packet in packets:
            w.write(T0 + dt, frame(packet))
    return path


def flows(path, **options) -> pd.DataFrame:
    features, metadata = extract_flows(path, **options)
    return pd.concat([metadata, features], axis=1)


# A connection: handshake, a request and a response, idle > 5 s, FIN both ways, last ACK; then a new SYN
# on the same ports, which starts the next flow
CONNECTION = [
    (0, c2s(SYN, window=29200, options=bytes.fromhex("020405b40402080a0000000000000000"))),
    (100, s2c(SYN | ACK, window=28960)),
    (150, c2s(ACK)),
    (300, c2s(PSH | ACK, 18)),
    (900, s2c(ACK)),
    (1200, s2c(PSH | ACK, 500)),
    (1300, c2s(ACK)),
    (7 * SECOND, c2s(FIN | ACK)),
    (7 * SECOND + 100, s2c(FIN | ACK, window=1000)),
    (7 * SECOND + 200, c2s(ACK)),
    (9 * SECOND, c2s(SYN)),
    (9 * SECOND + 50, s2c(SYN | ACK)),
]


def test_tcp_connection_closed_by_fin_both_ways(tmp_path):
    df = flows(write(tmp_path / "c.pcap", CONNECTION))
    assert len(df) == 2
    f = df.iloc[0]
    assert (f["Flow ID"], f["Src IP"], f["Src Port"], f["Dst IP"], f["Dst Port"]) == (
        f"{C}-{S}-40000-80-6", C, 40000, S, 80)
    assert f["Timestamp"] == "2017-07-05 12:00:00"
    expected = {
        "Protocol": 6, "Flow Duration": 7_000_200, "Total Fwd Packets": 6, "Total Backward Packets": 4,
        "Fwd Packets Length Total": 18, "Bwd Packets Length Total": 500,      # Ethernet padding not counted
        "Fwd Packet Length Max": 18, "Fwd Packet Length Min": 0, "Fwd Packet Length Mean": 3,
        "Fwd PSH Flags": 1, "Bwd PSH Flags": 1, "Fwd RST Flags": 0, "Bwd RST Flags": 0,
        "Fwd Header Length": 36 + 20 * 5, "Bwd Header Length": 80,      # the SYN has 16 bytes of options
        "FIN Flag Count": 2, "SYN Flag Count": 2, "ACK Flag Count": 9, "PSH Flag Count": 2,
        "Init Fwd Win Bytes": 29200,
        "Init Bwd Win Bytes": 1000,                    # the reference keeps the last backward window
        "Fwd Act Data Packets": 1, "Fwd Seg Size Min": 20,
        "Subflow Fwd Packets": 0, "Subflow Fwd Bytes": 1,  # every packet is a subflow: 6 // 10, 18 // 10
        "Active Mean": 1300, "Active Max": 1300, "Idle Mean": 6_998_700, "Idle Min": 6_998_700,
        "Flow IAT Max": 6_998_700, "Flow IAT Min": 50,
        "ICMP Code": -1, "ICMP Type": -1, "Total TCP Flow Time": 7_000_200,
    }
    assert {k: f[k] for k in expected} == expected
    assert f["Flow Bytes/s"] == pytest.approx(518 / 7.0002)
    assert f["Fwd Packet Length Std"] == pytest.approx(statistics.stdev([0, 0, 18, 0, 0, 0]))

    after = df.iloc[1]                              # the SYN after the teardown
    assert (after["Timestamp"], after["Total Fwd Packets"], after["Total Backward Packets"]) == (
        "2017-07-05 12:00:09", 1, 1)
    assert after["Total TCP Flow Time"] == 50


def test_rst_ends_the_connection(tmp_path):
    packets = [(0, c2s(SYN)), (200, s2c(RST | ACK)), (SECOND, c2s(SYN)), (SECOND + 100, s2c(RST | ACK))]
    df = flows(write(tmp_path / "c.pcap", packets))
    assert len(df) == 2
    assert df[["Fwd RST Flags", "Bwd RST Flags", "RST Flag Count", "Flow Duration"]].values.tolist() == [
        [0, 1, 1, 200], [0, 1, 1, 100]]


def test_timeout_splits_a_connection_and_keeps_its_direction(tmp_path):
    packets = [
        (0, c2s(SYN)), (100, s2c(SYN | ACK)), (200, c2s(ACK)),
        (60 * SECOND, c2s(PSH | ACK, 10)), (60 * SECOND + 100, s2c(ACK)),
        (130 * SECOND, s2c(PSH | ACK, 70, window=777)),      # > 120 s after the start; from the server
        (130 * SECOND + 200, c2s(ACK, window=555)),
    ]
    first, second = flows(write(tmp_path / "c.pcap", packets)).to_dict("records")
    assert first["Flow Duration"] == first["Total TCP Flow Time"] == 60_000_100
    # The second piece keeps the client as source though the server sent its first packet
    assert (second["Flow ID"], second["Src IP"], second["Dst IP"]) == (f"{C}-{S}-40000-80-6", C, S)
    assert (second["Total Fwd Packets"], second["Total Backward Packets"]) == (1, 1)
    assert (second["Init Bwd Win Bytes"], second["Init Fwd Win Bytes"], second["Fwd Seg Size Min"]) == (777, 0, 0)
    # Both pieces and the gap between them
    assert second["Total TCP Flow Time"] == 130_000_200


def test_icmp_flow_ends_only_when_code_and_type_both_change(tmp_path):
    packets = [
        (0, icmp(C, S, 8, 0)), (100, icmp(S, C, 0, 0)),     # echo request / reply: same code -> same flow
        (200, icmp(S, C, 11, 0)),                            # time exceeded, code 0 -> still the same flow
        (300, icmp(S, C, 3, 3)), (400, icmp(S, C, 3, 3)),    # both differ -> a new flow
    ]
    df = flows(write(tmp_path / "c.pcap", packets))
    assert df[["Flow ID", "Total Fwd Packets", "Total Backward Packets", "ICMP Type", "ICMP Code"]].values.tolist() == [
        [f"{C}-{S}-0-0-1", 1, 2, 8, 0],
        [f"{C}-{S}-0-0-1", 2, 0, 3, 3],                      # keyed as before, but its source is the server
    ]
    assert (df["Fwd Packets Length Total"] == 0).all() and (df["Src Port"] == 0).all()
    assert df.loc[1, "Src IP"] == S


def test_iat_active_and_idle_by_hand(tmp_path):
    times = [0, 1000, 3000, 10 * SECOND, 10 * SECOND + 2000, 10 * SECOND + 5000]
    packets = [(t, udp(S, C, 53, 5000, 40) if i == 4 else udp(C, S, 5000, 53, 20)) for i, t in enumerate(times)]
    f = flows(write(tmp_path / "c.pcap", packets)).iloc[0]
    flow_iat = [1000, 2000, 9_997_000, 2000, 3000]
    fwd_iat = [1000, 2000, 9_997_000, 5000]
    assert f["Flow IAT Mean"] == pytest.approx(statistics.mean(flow_iat))
    assert f["Flow IAT Std"] == pytest.approx(statistics.stdev(flow_iat))
    assert (f["Flow IAT Max"], f["Flow IAT Min"]) == (9_997_000, 1000)
    assert (f["Fwd IAT Total"], f["Fwd IAT Max"], f["Fwd IAT Min"]) == (10_005_000, 9_997_000, 1000)
    assert f["Fwd IAT Std"] == pytest.approx(statistics.stdev(fwd_iat))
    assert (f["Bwd IAT Total"], f["Bwd IAT Mean"]) == (0, 0)            # one backward packet
    # Active until the 9.997 s pause, which is idle; the last active stretch is never closed
    assert (f["Active Mean"], f["Active Std"], f["Idle Mean"], f["Idle Max"]) == (3000, 0, 9_997_000, 9_997_000)
    assert (f["Fwd Header Length"], f["Bwd Header Length"], f["Fwd Packets Length Total"]) == (40, 8, 100)


def test_bulk_by_hand(tmp_path):
    packets = [(t, udp(C, S, 5000, 9, 100)) for t in (0, 100, 200, 300, 400)] + [(500, udp(S, C, 9, 5000))]
    f = flows(write(tmp_path / "c.pcap", packets)).iloc[0]
    # Bulk from the 4th payload packet within 1 s: 5 packets, 500 bytes, 400 µs
    assert (f["Fwd Avg Bytes/Bulk"], f["Fwd Avg Packets/Bulk"], f["Fwd Avg Bulk Rate"]) == (500, 5, 1_250_000)
    assert (f["Bwd Avg Bytes/Bulk"], f["Bwd Avg Bulk Rate"]) == (0, 0)


def test_zero_duration_and_single_packet_flows(tmp_path):
    packets = [(0, udp(C, S, 1, 2, 10)), (0, udp(S, C, 2, 1, 10)), (5, udp(C, "10.9.9.9", 3, 4, 10))]
    path = write(tmp_path / "c.pcap", packets)
    stats = Counter()
    df = flows(path, stats=stats)
    assert len(df) == 1 and stats["short_flows"] == 1 and stats["flows"] == 1
    f = df.iloc[0]
    assert math.isinf(f["Flow Bytes/s"]) and math.isinf(f["Flow Packets/s"]) and f["Fwd Packets/s"] == 0
    # The reference writes single-packet flows; the training data has none
    single = flows(path, min_packets=1).iloc[1]
    assert math.isnan(single["Flow IAT Mean"]) and math.isinf(single["Flow Bytes/s"])


def test_ipv6_arp_and_other_protocols(tmp_path):
    ipv6 = bytes.fromhex("6000000000141140") + bytes(32) + udp_datagram(546, 547, b"\0" * 12)
    arp = bytes.fromhex("0001080006040001") + bytes(20)
    frames = [ethernet(udp(C, S, 1, 2, 5)), ethernet(ipv6, 0x86DD), ethernet(arp, 0x0806),
              ethernet(udp(S, C, 2, 1, 5)), ethernet(ip_packet(C, S, 47, b"\0" * 30)),
              ethernet(ip_packet(S, C, 47, b"\0" * 30)), ethernet(b"\x45\x00", pad=False)]   # cut short
    path = tmp_path / "c.pcap"
    with open(path, "wb") as f:
        w = PcapWriter(f)
        for i, frame in enumerate(frames):
            w.write(T0 + i, frame)
    stats = Counter()
    df = flows(path, stats=stats)
    assert df["Flow ID"].tolist() == [f"{C}-{S}-1-2-17", f"{C}-{S}-0-0-0"]       # GRE: protocol 0
    assert df["Protocol"].tolist() == [17, 0]
    assert (stats["packets"], stats["ipv4"], stats["ipv6"], stats["not_ip"], stats["malformed"]) == (7, 4, 1, 1, 1)


def test_fragments_become_protocol_0(tmp_path):
    datagram = udp_datagram(5000, 5004, b"\0" * 3000)
    chunks = [datagram[i:i + 1480] for i in range(0, len(datagram), 1480)]
    packets = [(i, ip_packet(C, S, 17, chunk, ident=7, fragment=i * 185, more_fragments=i < len(chunks) - 1))
               for i, chunk in enumerate(chunks)] + [(10, udp(S, C, 5004, 5000, 2))]
    df = flows(write(tmp_path / "c.pcap", packets), min_packets=1)
    by_id = df.set_index("Flow ID")
    assert by_id.loc[f"{C}-{S}-5000-5004-17", "Fwd Packets Length Total"] == 1480 - 8   # first fragment
    assert by_id.loc[f"{C}-{S}-0-0-0", "Total Fwd Packets"] == len(chunks) - 1


# ── link types and file formats ─────────────────────────────

def sll(packet):
    return struct.pack("!HHH8sH", 0, 1, 6, bytes(8), 0x0800) + packet


def sll2(packet):
    return struct.pack("!HHIHBB8s", 0x0800, 0, 1, 1, 0, 6, bytes(8)) + packet


def null(packet):
    return struct.pack("<I", 2) + packet


@pytest.mark.parametrize("linktype, frame, writer, options", [
    (1, lambda p: ethernet(p, vlan=5, pad=False), PcapWriter, {}),
    (113, sll, PcapWriter, {}),
    (276, sll2, PcapWriter, {}),
    (101, lambda p: p, PcapWriter, {}),
    (0, null, PcapWriter, {}),
    (1, ethernet, PcapWriter, {"nanos": True}),
    (1, ethernet, PcapngWriter, {}),
    (1, ethernet, PcapngWriter, {"tsresol": 9}),
])
def test_link_types_and_formats_give_the_same_flows(tmp_path, linktype, frame, writer, options):
    expected = flows(write(tmp_path / "ethernet.pcap", CONNECTION))
    path = write(tmp_path / "other.cap", CONNECTION, writer=writer, linktype=linktype, frame=frame, **options)
    pd.testing.assert_frame_equal(flows(path), expected)


def test_unsupported_link_type_is_counted(tmp_path):
    stats = Counter()
    path = write(tmp_path / "wifi.pcap", CONNECTION, linktype=127)          # radiotap
    assert flows(path, stats=stats).empty and stats["unsupported_link"] == len(CONNECTION)


def test_truncated_last_packet_is_ignored(tmp_path):
    path = write(tmp_path / "c.pcap", CONNECTION)
    path.write_bytes(path.read_bytes()[:-10])
    assert flows(path).iloc[0]["Total Fwd Packets"] == 6                   # the first flow is complete


@pytest.mark.parametrize("content", [b"", b"abc", b"not a capture at all", bytes.fromhex("d4c3b2a1") + b"\0" * 8])
def test_not_a_capture(tmp_path, content):
    path = tmp_path / "x.pcap"
    path.write_bytes(content)
    with pytest.raises(CaptureError):
        list(iter_flows(path))


# ── emitting timed-out flows early ──────────────────────────

def test_early_emission_changes_nothing(tmp_path, monkeypatch):
    """Flows past the timeout leave the table during the capture; the output must stay the reference's."""
    packets = [(0, udp(C, S, 7, 8, 10)), (10, udp(S, C, 8, 7, 10)),           # UDP, picked up again later
               (20, c2s(SYN)), (30, s2c(SYN | ACK)), (40, c2s(ACK))]           # TCP, continued later
    packets += [(t * SECOND, udp("10.1.1.1", "10.2.2.2", 1000 + t, 53, 30)) for t in range(1, 300, 3)]
    packets += [(200 * SECOND, udp(S, C, 8, 7, 10)), (201 * SECOND, udp(C, S, 7, 8, 10)),
                (250 * SECOND, s2c(PSH | ACK, 5)), (251 * SECOND, c2s(ACK))]
    path = write(tmp_path / "c.pcap", sorted(packets, key=lambda p: p[0]))

    ended = []
    original = generator._Ended.__init__
    monkeypatch.setattr(generator._Ended, "__init__", lambda self, flow: (ended.append(flow.key), original(self, flow))[1])
    early = flows(path, min_packets=1)
    assert len(ended) > 2                                     # flows did leave the table early

    monkeypatch.setattr(generator, "SWEEP_MARGIN", 10 ** 15)  # never: as the reference
    late = flows(path, min_packets=1)
    key = ["Flow ID", "Timestamp"]
    pd.testing.assert_frame_equal(early.sort_values(key).reset_index(drop=True),
                                  late.sort_values(key).reset_index(drop=True))
    udp_pieces = early[early["Flow ID"] == f"{C}-{S}-7-8-17"]
    assert len(udp_pieces) == 2 and udp_pieces.iloc[1]["Src IP"] == S          # Flow ID keeps its orientation
    tcp_pieces = early[early["Flow ID"] == f"{C}-{S}-40000-80-6"]
    assert tcp_pieces["Total TCP Flow Time"].tolist() == [20, 251 * SECOND - 20]


# ── building blocks ─────────────────────────────────────────

def test_running_statistics_match_sample_statistics():
    values = [3, 1000, 7, 7, 250_000, 12]
    s = Stat()
    for v in values:
        s.add(v)
    assert (s.n, s.total, s.lo, s.hi) == (6, sum(values), 3, 250_000)
    assert s.mean == pytest.approx(statistics.mean(values), rel=1e-15)
    assert s.std == pytest.approx(statistics.stdev(values), rel=1e-12)
    assert s.variance == pytest.approx(statistics.variance(values), rel=1e-12)
    one, none = Stat(), Stat()
    one.add(5)
    assert (one.mean, one.std, one.variance) == (5, 0, 0)
    assert math.isnan(none.mean) and math.isnan(none.std) and math.isnan(none.hi)


@pytest.mark.parametrize("us, text", [
    (T0, "2017-07-05 12:00:00"), (T0 + 123_000, "2017-07-05 12:00:00.123"),
    (T0 + 123_456, "2017-07-05 12:00:00.123456"), (T0 + 1, "2017-07-05 12:00:00.000001"),
])
def test_timestamps_as_the_reference_prints_them(us, text):
    assert java_timestamp(us) == text


def test_cli_writes_csv_and_parquet(tmp_path, capsys):
    path = write(tmp_path / "c.pcap", CONNECTION)
    assert cli([str(path), "-o", str(tmp_path / "flows.csv")]) == 0
    csv = pd.read_csv(tmp_path / "flows.csv")
    assert list(csv.columns[6:]) == list(FEATURES) and len(csv) == 2
    assert cli([str(path), "-o", str(tmp_path / "flows.parquet"), "--min-packets", "1"]) == 0
    assert len(pd.read_parquet(tmp_path / "flows.parquet")) == 2
    assert "12 packets (12 IPv4) -> 2 flows" in capsys.readouterr().err
    (tmp_path / "bad.pcap").write_bytes(b"nope")
    assert cli([str(tmp_path / "bad.pcap")]) == 1
