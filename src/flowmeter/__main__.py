"""
python -m src.flowmeter capture.pcap -o flows.csv     (or .parquet)

Writes the flows of a capture with the training column names, then prints what was read and how long
it took.
"""

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from . import MIN_PACKETS, CaptureError, flow_batches
from .schema import COLUMNS


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.flowmeter", description=__doc__.strip().splitlines()[0])
    parser.add_argument("capture", type=Path, help="pcap or pcapng file")
    parser.add_argument("-o", "--output", type=Path, help="flows.csv or flows.parquet (default: <capture>.flows.csv)")
    parser.add_argument("--min-packets", type=int, default=MIN_PACKETS,
                        help=f"leave out flows with fewer packets (default {MIN_PACKETS}; the reference tool writes all)")
    args = parser.parse_args(argv)
    output = args.output or args.capture.with_name(args.capture.name + ".flows.csv")

    stats, start, writer, n = Counter(), time.perf_counter(), None, 0
    try:
        for batch in flow_batches(args.capture, min_packets=args.min_packets, stats=stats):
            if output.suffix == ".parquet":
                import pyarrow as pa
                import pyarrow.parquet as pq
                table = pa.Table.from_pandas(batch, preserve_index=False)
                writer = writer or pq.ParquetWriter(output, table.schema, compression="zstd")
                writer.write_table(table)
            else:
                batch.to_csv(output, mode="a" if n else "w", header=not n, index=False)
            n += len(batch)
    except CaptureError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        if writer is not None:
            writer.close()

    elapsed = time.perf_counter() - start
    skipped = {k: v for k, v in stats.items() if k in ("ipv6", "not_ip", "malformed", "unsupported_link") and v}
    print(f"{stats['packets']:,} packets ({stats['ipv4']:,} IPv4) -> {n:,} flows in {elapsed:.1f} s "
          f"({stats['packets'] / max(elapsed, 1e-9):,.0f} packets/s); "
          f"{stats['short_flows']:,} flows under {args.min_packets} packets left out", file=sys.stderr)
    if skipped:
        print("skipped packets: " + ", ".join(f"{k} {v:,}" for k, v in skipped.items()), file=sys.stderr)
    if n == 0:
        empty = pd.DataFrame(columns=COLUMNS)
        empty.to_parquet(output, index=False) if output.suffix == ".parquet" else empty.to_csv(output, index=False)
    print(f"wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
