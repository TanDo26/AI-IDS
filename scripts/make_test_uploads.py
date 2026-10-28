"""
Write labelled test uploads: a number of files per class, as CICFlowMeter CSVs or pcap / pcapng
captures, plus manifest.csv naming each file's class (README "Test uploads").

Every file holds flows of one class, taken from the held-out rows (test + validation) of a split, so
the model never trained on them. The files hold only what the model reads (no Label column), as real
traffic would: which class a file holds is only in manifest.csv.
- csv: the rows' features under the Java CICFlowMeter's column names, with made-up endpoints.
- pcap / pcapng: each row is turned back into packets that src.flowmeter (and the Java tool) reads
  as one flow with the row's packet counts, payload sizes (total, min, max, about the std), duration
  and inter-arrival times, TCP flags, header sizes and windows. Of a few random arrangements, the one
  whose extracted features come closest to the row is kept. Bulk and active/idle values follow from
  the timing and come out close rather than equal, so now and then a flow is classed differently.
  Rows that continue a connection split by the 120 s timeout are left out (they need its earlier
  pieces), and so are flows of more than 5,000 packets.

With a model bundle (by default the newest in model_store/), each written file is read back as the
server reads uploads and predicted; the manifest says how many flows came out as their class and
which decisions (benign / unknown / known_attack) the results page will show. --only-matching keeps
only flows the model puts in their class, for demos.

    python scripts/make_test_uploads.py DDoS=3 Portscan=2 Benign=1                   # 200-flow CSVs
    python scripts/make_test_uploads.py "DoS Hulk=2" ssh-patator=1 --format pcap --flows 100
    python scripts/make_test_uploads.py all=1 --format pcapng --only-matching
"""
import re
import sys
import json
import math
import random
import argparse
from itertools import zip_longest
from pathlib import Path

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.flowmeter import extract_flows
from src.flowmeter.flow import java_timestamp
from src.flowmeter.generator import FlowGenerator
from src.flowmeter.packet import ACK, CWR, ECE, FIN, ICMP, PSH, RST, SYN, TCP, UDP, URG, Packet
from src.flowmeter.pcapwriter import (PcapngWriter, PcapWriter, ethernet, icmp_frame, ip_packet, tcp_frame,
                                      udp_frame)
from src.flowmeter.schema import FEATURES
from src.inference.bundle import load_bundle
from src.inference.engine import InferenceEngine
from src.inference.schema import JAVA_TO_TRAINING
from src.pipeline_config import config_path

START_US = 1_499_256_000_000_000            # 2017-07-05 12:00 UTC, as in make_test_capture.py
SPAN_US = 60_000_000                        # a file's flows start within its first minute
MAX_PACKETS = 5000                          # longer flows are left out of captures
SEARCH_PACKETS = 4000                       # packets simulated per flow while searching
MAX_TRIES = 24
MAX_UPLOAD_BYTES = 100_000_000              # the server's limit (IDS_MAX_UPLOAD_MB)
COL = {name: i for i, name in enumerate(FEATURES)}
JAVA_NAMES = {train: java for java, train in JAVA_TO_TRAINING.items()}
DST_PORTS = {"Botnet": 8080, "FTP-Patator": 21, "SSH-Patator": 22, "Heartbleed": 444, "Infiltration": 444}
SCANS = ("Portscan", "Infiltration - Portscan")
BENIGN_SERVERS = ("8.8.8.8", "142.250.4.100", "151.101.1.69", "104.16.132.229")
VICTIM = "192.168.10.50"
SIM_SRC, SIM_DST = bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2])


def _key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _slug(name) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# ── rows -> packets ──

def _int(x) -> int:
    return int(round(float(x)))


def _spread(n, total, lo, hi, std) -> list[int]:
    """n integers in [lo, hi] summing to `total`, with about the given sample standard deviation."""
    if n <= 0:
        return []
    total, lo, std = max(0, _int(total)), max(0, _int(lo)), float(std)
    hi = max(lo, _int(hi))
    if n == 1:
        return [total]
    total = min(max(total, n * lo), n * hi)
    if n == 2:
        second = min(hi, total - lo)
        return [total - second, second]
    # min and max once each; the rest alternate around their mean to make up the variance
    k = n - 2
    rest_mean = (total - lo - hi) / k
    sum_squares = (n - 1) * std * std + total * total / n
    spread = math.sqrt(max(0.0, (sum_squares - lo * lo - hi * hi) / k - rest_mean * rest_mean))
    signs = [(-1) ** i for i in range(k - k % 2)] + [0] * (k % 2)
    values = [lo, hi] + [min(hi, max(lo, round(rest_mean + spread * s))) for s in signs]
    diff = total - sum(values)
    while diff:
        sign = 1 if diff > 0 else -1
        movable = [i for i in range(2, n) if (values[i] < hi if sign > 0 else values[i] > lo)]
        if not movable:
            break
        step = max(1, abs(diff) // len(movable))
        for i in movable:
            room = hi - values[i] if sign > 0 else values[i] - lo
            d = min(step, room, abs(diff))
            values[i] += sign * d
            diff -= sign * d
            if not diff:
                break
    return values


def _headers(n, total, minimum) -> list[int]:
    """TCP header sizes (20-60, multiples of 4) summing to about `total`; one stays at the minimum."""
    if n <= 0:
        return []
    base = int(minimum) if minimum and 20 <= minimum <= 60 and minimum % 4 == 0 else 20
    sizes = [base] * n
    extra = max(0, int(total) - base * n) // 4
    grow = range(n - 1) if n > 1 else range(0)
    while extra > 0:
        before = extra
        for i in grow:
            if extra and sizes[i] < 60:
                sizes[i] += 4
                extra -= 1
        if extra == before:
            break
    return sizes


def _arrange(v, rng) -> list[tuple]:
    """One random arrangement of a row's packets: (µs offset, forward, payload, header, window, flags)."""
    proto = int(v[COL["Protocol"]])
    n_fwd, n_bwd = int(v[COL["Total Fwd Packets"]]), int(v[COL["Total Backward Packets"]])
    if proto in (TCP, UDP):
        fwd_sizes = _spread(n_fwd, v[COL["Fwd Packets Length Total"]], v[COL["Fwd Packet Length Min"]],
                            v[COL["Fwd Packet Length Max"]], v[COL["Fwd Packet Length Std"]])
        bwd_sizes = _spread(n_bwd, v[COL["Bwd Packets Length Total"]], v[COL["Bwd Packet Length Min"]],
                            v[COL["Bwd Packet Length Max"]], v[COL["Bwd Packet Length Std"]])
    else:                                    # ICMP and other protocols carry no payload for the flow meter
        fwd_sizes, bwd_sizes = [0] * n_fwd, [0] * n_bwd
    rng.shuffle(fwd_sizes)
    rng.shuffle(bwd_sizes)
    # Fwd Act Data Packets counts the forward packets after the first that carry data
    with_data = sum(s > 0 for s in fwd_sizes)
    first_has_data = with_data > v[COL["Fwd Act Data Packets"]]
    for i, size in enumerate(fwd_sizes):
        if (size > 0) == first_has_data:
            fwd_sizes[0], fwd_sizes[i] = fwd_sizes[i], fwd_sizes[0]
            break

    fwd_gaps = _spread(n_fwd - 1, v[COL["Fwd IAT Total"]], v[COL["Fwd IAT Min"]], v[COL["Fwd IAT Max"]],
                       v[COL["Fwd IAT Std"]])
    bwd_gaps = _spread(n_bwd - 1, v[COL["Bwd IAT Total"]], v[COL["Bwd IAT Min"]], v[COL["Bwd IAT Max"]],
                       v[COL["Bwd IAT Std"]])
    rng.shuffle(fwd_gaps)
    rng.shuffle(bwd_gaps)
    fwd_t, bwd_t = [0], [0]
    for gap in fwd_gaps:
        fwd_t.append(fwd_t[-1] + gap)
    for gap in bwd_gaps:
        bwd_t.append(bwd_t[-1] + gap)
    if n_bwd:
        duration = _int(v[COL["Flow Duration"]])
        room = max(0, duration - bwd_t[-1])
        if fwd_t[-1] < duration:             # the backward packets end the flow
            first_bwd = room
        else:                                # the forward ones do; the reply starts somewhere in between
            r = rng.random()
            first_bwd = (min(room, _int(v[COL["Flow IAT Min"]])) if r < 0.4 else
                         rng.randint(0, room) if r < 0.7 else int(room * rng.random() ** 3))
        bwd_t = [first_bwd + t for t in bwd_t]
    else:
        bwd_t = []
    # Forward first on equal times: the flow's first packet defines its direction
    order = sorted([(t, 0, i) for i, t in enumerate(fwd_t)] + [(t, 1, j) for j, t in enumerate(bwd_t)])

    fwd_flags, bwd_flags = [0] * n_fwd, [0] * n_bwd
    if proto == TCP:
        flags = (fwd_flags, bwd_flags)

        def mark(packets, bit, count):
            for d, i in packets[:max(0, int(count))]:
                flags[d][i] |= bit

        in_time = [(d, i) for _, d, i in order]
        sizes = (fwd_sizes, bwd_sizes)
        with_payload = sorted(in_time, key=lambda p: sizes[p[0]][p[1]] == 0)
        # SYNs first and FIN / RST last, so no SYN follows a teardown (that would start a new flow)
        mark(in_time, SYN, v[COL["SYN Flag Count"]])
        mark([(0, i) for i in range(n_fwd - 1, 0, -1)], RST, v[COL["Fwd RST Flags"]])
        mark([(1, j) for j in range(n_bwd - 1, -1, -1)], RST, v[COL["Bwd RST Flags"]])
        if v[COL["RST Flag Count"]] > v[COL["Fwd RST Flags"]] + v[COL["Bwd RST Flags"]]:
            fwd_flags[0] |= RST              # RST counts per direction skip the flow's first packet
        last_first = [p for pair in zip_longest([(0, i) for i in range(n_fwd - 1, -1, -1)],
                                                [(1, j) for j in range(n_bwd - 1, -1, -1)]) for p in pair if p]
        mark(last_first, FIN, v[COL["FIN Flag Count"]])
        mark([p for p in with_payload if p[0] == 0], PSH, v[COL["Fwd PSH Flags"]])
        mark([p for p in with_payload if p[0] == 1], PSH, v[COL["Bwd PSH Flags"]])
        mark([p for p in with_payload if p[0] == 0], URG, v[COL["Fwd URG Flags"]])
        mark([p for p in with_payload if p[0] == 1], URG, v[COL["Bwd URG Flags"]])
        mark(in_time, CWR, v[COL["CWR Flag Count"]])
        mark(in_time, ECE, v[COL["ECE Flag Count"]])
        # ACK on all but the opening SYN and bare RSTs, as many as the row has
        without = n_fwd + n_bwd - int(v[COL["ACK Flag Count"]])
        preferred = sorted(in_time, key=lambda p: flags[p[0]][p[1]] not in (SYN, RST))   # stable: time order
        no_ack = set(preferred[:max(0, without)])
        for p in in_time:
            if p not in no_ack:
                flags[p[0]][p[1]] |= ACK
        fwd_hdr = _headers(n_fwd, v[COL["Fwd Header Length"]], v[COL["Fwd Seg Size Min"]])
        bwd_hdr = _headers(n_bwd, v[COL["Bwd Header Length"]], _int(v[COL["Bwd Header Length"]]) // max(1, n_bwd) // 4 * 4)
    else:
        header = 8 if proto == UDP else 0
        fwd_hdr, bwd_hdr = [header] * n_fwd, [header] * n_bwd
    windows = (min(65535, max(0, int(v[COL["Init Fwd Win Bytes"]]))) if proto == TCP else 0,
               min(65535, max(0, int(v[COL["Init Bwd Win Bytes"]]))) if proto == TCP else 0)

    packets = []
    for t, d, i in order:
        size, hdr, flg = ((fwd_sizes[i], fwd_hdr[i], fwd_flags[i]) if d == 0 else
                          (bwd_sizes[i], bwd_hdr[i], bwd_flags[i]))
        packets.append((t, d == 0, min(size, 65535 - 20 - max(hdr, 8)), hdr, windows[d], flg))
    return packets


def _simulate(proto, icmp, packets) -> list:
    """What the flow meter makes of these packets: its flows (one, unless the arrangement split it)."""
    generator = FlowGenerator()
    for t, forward, payload, header, window, flags in packets:
        src, dst, sport, dport = (SIM_SRC, SIM_DST, 40000, 80) if forward else (SIM_DST, SIM_SRC, 80, 40000)
        if proto == TCP:
            p = Packet(START_US + t, src, dst, sport, dport, TCP, payload, header, window, flags)
        elif proto == UDP:
            p = Packet(START_US + t, src, dst, sport, dport, UDP, payload, 8)
        elif proto == ICMP:
            p = Packet(START_US + t, src, dst, proto=ICMP, icmp_type=icmp[0], icmp_code=icmp[1])
        else:
            p = Packet(START_US + t, src, dst)
        generator.add(p)
    generator.flush()
    return generator.finished


def _distance(got, want, columns) -> float:
    """Sum of relative differences over the given feature positions."""
    error = 0.0
    for c in columns:
        a, b = got[c], want[c]
        if a == b or (a != a and b != b):
            continue
        if a != a or b != b or math.isinf(a) or math.isinf(b):
            error += 1
        else:
            error += abs(a - b) / max(abs(a), abs(b))
    return error


class Replay:
    """A row turned into packets: the closest of a few arrangements."""

    def __init__(self, v, rng, columns):
        self.proto = int(v[COL["Protocol"]])
        self.icmp = (max(0, int(v[COL["ICMP Type"]])), max(0, int(v[COL["ICMP Code"]])))
        n = int(v[COL["Total Fwd Packets"]] + v[COL["Total Backward Packets"]])
        best = None
        for _ in range(max(4, min(MAX_TRIES, SEARCH_PACKETS // max(1, n)))):
            packets = _arrange(v, rng)
            flows = _simulate(self.proto, self.icmp, packets)
            features = flows[0].features()
            score = _distance(features, v, columns) + 10 * (len(flows) - 1)
            if best is None or score < best[0]:
                best = (score, packets, features)
            if score == 0:
                break
        self.distance, self.packets, self.features = best


def _endpoints(name, proto, n, rng) -> tuple:
    """(src, dst, sport, dport) of a file's n-th flow; its own source address keeps every key apart."""
    src = f"{'192.168' if name == 'Benign' else '172.16'}.{(n >> 8) & 255}.{n & 255}"
    dst = rng.choice(BENIGN_SERVERS) if name == "Benign" else VICTIM
    if proto not in (TCP, UDP):
        return src, dst, 0, 0
    if name == "Benign":
        dport = 53 if proto == UDP else rng.choice((80, 443, 443, 8080))
    else:
        dport = rng.randint(1, 65535) if name in SCANS else DST_PORTS.get(name, 80)
    return src, dst, rng.randint(1024, 65535), dport


def write_capture(path, fmt, name, replays, rng) -> int:
    records = []
    for k, replay in enumerate(replays):
        src, dst, sport, dport = _endpoints(name, replay.proto, k + 1, rng)
        start = START_US + rng.randrange(SPAN_US)
        seq = {True: rng.getrandbits(32), False: rng.getrandbits(32)}
        for i, (t, forward, payload, header, window, flags) in enumerate(replay.packets):
            a, b, pa, pb = (src, dst, sport, dport) if forward else (dst, src, dport, sport)
            if replay.proto == TCP:
                frame = tcp_frame(a, b, pa, pb, flags, bytes(payload), seq=seq[forward] & 0xFFFFFFFF,
                                  ack=seq[not forward] & 0xFFFFFFFF if flags & ACK else 0, window=window,
                                  options=b"\x01" * (header - 20))
                seq[forward] += payload + (1 if flags & (SYN | FIN) else 0)
            elif replay.proto == UDP:
                frame = udp_frame(a, b, pa, pb, bytes(payload))
            elif replay.proto == ICMP:
                frame = icmp_frame(a, b, *replay.icmp)
            else:                            # GRE: any protocol but TCP/UDP/ICMP is protocol 0 to the flow meter
                frame = ethernet(ip_packet(a, b, 47, b""))
            records.append((start + t, k, i, frame))
    records.sort(key=lambda r: r[:3])
    with open(path, "wb") as f:
        writer = PcapWriter(f) if fmt == "pcap" else PcapngWriter(f)
        for ts, _, _, frame in records:
            writer.write(ts, frame)
    return len(records)


def write_csv(path, name, rows: pd.DataFrame, rng) -> None:
    """Rows in the Java CICFlowMeter's layout (its column names, Protocol before Timestamp), without a Label."""
    meta = [_endpoints(name, int(p), k + 1, rng) for k, p in enumerate(rows["Protocol"])]
    proto = rows["Protocol"].astype(int).to_numpy()
    df = pd.DataFrame({
        "Flow ID": [f"{s}-{d}-{sp}-{dp}-{p}" for (s, d, sp, dp), p in zip(meta, proto)],
        "Src IP": [m[0] for m in meta], "Src Port": [m[2] for m in meta],
        "Dst IP": [m[1] for m in meta], "Dst Port": [m[3] for m in meta],
        "Protocol": proto,
        "Timestamp": sorted(java_timestamp(START_US + rng.randrange(SPAN_US)) for _ in meta),
    })
    features = rows[[f for f in FEATURES if f != "Protocol"]].reset_index(drop=True)
    df = pd.concat([df, features.rename(columns=lambda c: JAVA_NAMES.get(c, c))], axis=1)
    df.to_csv(path, index=False)


# ── classes, rows, model ──

def parse_specs(specs, labels) -> list[tuple[int, int]]:
    """'DDoS=3', 'dos-hulk=2', '4', 'all=1' -> [(class id, files)] in the order given."""
    by_key = {_key(name): cid for cid, name in labels.items()}
    counts = {}
    for spec in specs:
        name, sep, count = spec.rpartition("=")
        if not sep:
            name, count = spec, "1"
        if not count.isdigit() or int(count) < 1:
            sys.exit(f"  {spec!r}: the count after '=' must be a whole number of files, 1 or more")
        if _key(name) == "all":
            ids = list(labels)
        elif name.strip().isdigit() and int(name) in labels:
            ids = [int(name)]
        elif _key(name) in by_key:
            ids = [by_key[_key(name)]]
        else:
            sys.exit(f"  Unknown class {name!r}. Classes: " + ", ".join(labels.values()))
        for cid in ids:
            counts[cid] = counts.get(cid, 0) + int(count)
    return list(counts.items())


def load_rows(split):
    """Held-out rows (test + validation) of a split, their classes and the class names."""
    with open(config_path(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    ds_name = config["active_dataset"]
    split_dir = Path(config["output"]["splits_dir"].format(dataset_name=ds_name)) / split
    with open(Path(config["datasets"][ds_name]["data_dir"]) / "label_mapping.json", "r", encoding="utf-8") as f:
        labels = {int(k): v for k, v in json.load(f)["int_to_label"].items()}
    X = pd.concat([pd.read_parquet(split_dir / f"X_{s}.parquet") for s in ("test", "val")], ignore_index=True)
    y = pd.concat([pd.read_parquet(split_dir / f"y_{s}.parquet")["MulticlassLabel"] for s in ("test", "val")],
                  ignore_index=True)
    return X[list(FEATURES)], y, labels


def load_engine(choice):
    if choice == "none":
        return None
    if choice == "auto":
        manifests = sorted((PROJECT_ROOT / "model_store").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
        if not manifests:
            print("  No bundle in model_store/: files are written without checking them against a model")
            return None
        choice = manifests[-1].parent
    bundle = load_bundle(choice)
    print(f"  Checking files with {bundle.bundle_id}")
    return InferenceEngine(bundle)


def predicted_classes(engine, features: pd.DataFrame) -> list[str]:
    return engine.predict(features).loc[:, "class_name"].tolist()


def read_back(path, fmt) -> pd.DataFrame:
    """The file's flows as the server reads an upload."""
    if fmt == "csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    features, metadata = extract_flows(path)
    return pd.concat([metadata, features], axis=1)


# ── main ──

def main(specs, fmt, flows, split, out, bundle, only_matching, seed):
    X, y, labels = load_rows(split)
    plan = parse_specs(specs, labels)
    engine = load_engine(bundle)
    if only_matching and engine is None:
        sys.exit("  --only-matching needs a model bundle")
    columns = ([COL[f] for f in engine.required] if engine else list(range(len(FEATURES))))
    rng = random.Random(seed)
    values = X.to_numpy(dtype=float)
    capture = fmt != "csv"
    if capture:
        packets = X["Total Fwd Packets"] + X["Total Backward Packets"]
        continued = (X["Protocol"] == TCP) & (X["Total TCP Flow Time"] > X["Flow Duration"])
        usable = (packets <= MAX_PACKETS) & ~continued
    out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for cid, n_files in plan:
        name = labels[cid]
        mask = (y == cid) & usable if capture else (y == cid)
        pool = list(X.index[mask])
        if not pool:
            print(f"  {name}: no held-out flows{' that can be replayed' if capture else ''}; skipped")
            continue
        rng.shuffle(pool)
        cursor = 0
        for n in range(1, n_files + 1):
            chosen, size, tried, full = [], 0, 0, False
            # A file wants `flows` flows; the pool may be smaller (rows are then reused) or the model may
            # disagree with some (--only-matching): stop after two passes over the pool
            while len(chosen) < flows and not full and tried < 2 * max(len(pool), flows):
                batch = [pool[(cursor + i) % len(pool)] for i in range(min(256, flows - len(chosen)))]
                cursor += len(batch)
                tried += len(batch)
                if capture:
                    items = [(r, Replay(values[r], rng, columns)) for r in batch]
                    features = pd.DataFrame([rep.features for _, rep in items], columns=list(FEATURES))
                else:
                    items = [(r, None) for r in batch]
                    features = X.loc[batch].reset_index(drop=True)
                keep = ([c == name for c in predicted_classes(engine, features)] if only_matching
                        else [True] * len(items))
                for (r, rep), ok in zip(items, keep):
                    if not ok:
                        continue
                    if capture:   # Ethernet + IP + TCP/UDP header + payload + 16-byte record header, about
                        flow_bytes = sum(50 + p[2] + p[3] for p in rep.packets)
                        if size + flow_bytes > 0.95 * MAX_UPLOAD_BYTES:
                            full = True
                            break
                        size += flow_bytes
                    chosen.append((r, rep))
                    if len(chosen) == flows:
                        break
            if not chosen:
                print(f"  {name}: the model put none of {tried} tried flows in this class; no file written")
                break
            path = out / f"{_slug(name)}-{n:02d}.{fmt}"
            n_packets = ""
            if capture:
                n_packets = write_capture(path, fmt, name, [rep for _, rep in chosen], rng)
            else:
                write_csv(path, name, X.loc[[r for r, _ in chosen]], rng)
            entry = {"file": path.name, "format": fmt, "class": name, "flows": len(chosen),
                     "unique_rows": len({r for r, _ in chosen}), "packets": n_packets,
                     "size_mb": round(path.stat().st_size / 1e6, 2)}
            if engine:
                result = engine.predict(read_back(path, fmt))
                hits = int((result["class_name"] == name).sum())
                decisions = result["decision"].value_counts()
                entry.update(flows_read=len(result), predicted_as_class=hits,
                             match_rate=round(hits / len(result), 3) if len(result) else 0.0,
                             # what the results page's tiles will show, in their order
                             decisions=" ".join(f"{d}={decisions[d]}" for d in ("benign", "unknown", "known_attack")
                                                if d in decisions),
                             model=engine.bundle.bundle_id)
            manifest.append(entry)
            note = ""
            if len(chosen) < flows:
                note = " (upload size limit)" if full else f" (the model agreed on only {len(chosen)})"
            if entry["unique_rows"] < len(chosen):
                note += f" from {entry['unique_rows']} distinct rows"
            check = f"  model: {entry['predicted_as_class']}/{entry['flows_read']} {name}" if engine else ""
            print(f"  {path.name:<34} {len(chosen):>6,} flows  {entry['size_mb']:>7} MB{check}{note}")
            if path.stat().st_size > MAX_UPLOAD_BYTES:
                print("    larger than the 100 MB upload limit; use fewer --flows")

    if manifest:
        pd.DataFrame(manifest).to_csv(out / "manifest.csv", index=False)
        print(f"  {len(manifest)} files and manifest.csv -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Write labelled CICFlowMeter CSV or pcap/pcapng test uploads, one class per file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="CLASS=COUNT: a class name (any case; spaces or dashes optional, e.g. dos-hulk) or its id, and how\n"
               "many files of it; 'all=1' writes one file of every class.")
    parser.add_argument("files", nargs="+", metavar="CLASS=COUNT")
    parser.add_argument("--format", default="csv", choices=["csv", "pcap", "pcapng"])
    parser.add_argument("--flows", type=int, default=200, help="Flows per file (default 200)")
    parser.add_argument("--split", default="random", choices=["random", "temporal"],
                        help="Whose held-out rows to use (default random, EXP-59's)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "test_uploads")
    parser.add_argument("--bundle", default="auto",
                        help="Bundle directory to check the files with; 'auto' (the newest in model_store/) or 'none'")
    parser.add_argument("--only-matching", action="store_true",
                        help="Keep only flows the model puts in their class")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.flows < 1:
        parser.error("--flows must be 1 or more")
    main(args.files, args.format, args.flows, args.split, args.out, args.bundle, args.only_matching, args.seed)
