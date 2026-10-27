"""
Flow extractor: a pcap / pcapng capture -> CICFlowMeter flows with the training features.

A Python port of the corrected CICFlowMeter (Engelen et al.) at commit 13a0615, the version the
CIC-IDS2017 training data was made with; see generator.py, flow.py and reader.py for what is replicated.

    for batch in flow_batches("capture.pcap"):      # DataFrames: METADATA then FEATURES columns
        ...
    features, metadata = extract_flows("capture.pcap")

Flows with a single packet are left out by default: the training data has none (min_packets=1 keeps
them, as the reference tool writes them).
"""

from collections import Counter
from collections.abc import Callable, Iterator

import pandas as pd

from .generator import ACTIVITY_TIMEOUT, FLOW_TIMEOUT, FlowGenerator
from .reader import CaptureError, read_packets
from .schema import COLUMNS, FEATURES, METADATA

__all__ = ["CaptureError", "COLUMNS", "FEATURES", "METADATA", "extract_flows", "flow_batches", "iter_flows"]

MIN_PACKETS = 2
BATCH_SIZE = 50_000


def iter_flows(path, *, min_packets=MIN_PACKETS, flow_timeout=FLOW_TIMEOUT, activity_timeout=ACTIVITY_TIMEOUT,
               stats: Counter | None = None, progress: Callable[[float], None] | None = None) -> Iterator[tuple]:
    """One row per flow, in the order flows end: METADATA values then FEATURES values.
    `stats` counts packets read and skipped, and flows (`flows`, `short_flows` left out)."""
    stats = Counter() if stats is None else stats
    generator = FlowGenerator(flow_timeout, activity_timeout)
    finished = generator.finished

    def drain():
        for flow in finished:
            if flow.packets >= min_packets:
                stats["flows"] += 1
                yield flow.metadata() + flow.features()
            else:
                stats["short_flows"] += 1
        finished.clear()

    for packet in read_packets(path, stats, progress):
        generator.add(packet)
        if finished:
            yield from drain()
    generator.flush()
    yield from drain()


def flow_batches(path, batch_size=BATCH_SIZE, **options) -> Iterator[pd.DataFrame]:
    """iter_flows() as DataFrames of up to batch_size rows (columns: COLUMNS)."""
    rows = []
    for row in iter_flows(path, **options):
        rows.append(row)
        if len(rows) == batch_size:
            yield _frame(rows)
            rows = []
    if rows:
        yield _frame(rows)


def extract_flows(path, **options) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All flows of a capture as (features, metadata) frames with the same index."""
    frames = list(flow_batches(path, **options))
    flows = pd.concat(frames, ignore_index=True) if frames else _frame([])
    return flows[list(FEATURES)], flows[list(METADATA)]


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame.from_records(rows, columns=COLUMNS)
    df[list(FEATURES)] = df[list(FEATURES)].astype("float64")
    return df
