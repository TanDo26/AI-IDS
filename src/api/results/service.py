"""
Reading an upload's results: <results_dir>/<upload_id>/flows.parquet (written by
src/api/uploads/processing.py), queried with DuckDB.

SQL is assembled only from column names that are whitelisted or read from the file's own
schema, always quoted; every value (path, filters, limits) is a bound parameter.
"""

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from src.api.db.models import Upload
from src.api.settings import Settings
from src.api.uploads.processing import PREDICTION_COLUMNS, RESULTS_FILE
from src.api.uploads.service import results_dir
from src.inference.schema import LABEL_COLUMN, METADATA_COLUMNS

SORTABLE = ("row", "decision", "reason", "class_name", "confidence", "attack_score", "anomaly_score",
            "imputed_cells")
EXPORT_BATCH_ROWS = 50_000


class ResultsUnavailable(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


@dataclass
class Layout:
    metadata: list[str]      # Flow ID, IPs, ports, timestamp: whichever the upload had
    has_label: bool
    features: list[str]      # the model input features

    def columns(self, features: bool = False) -> list[str]:
        """Output columns, in order: row, metadata, Label, predictions (, features)."""
        return ["row", *self.metadata, *([LABEL_COLUMN] if self.has_label else []), *PREDICTION_COLUMNS,
                *(self.features if features else [])]


def results_file(settings: Settings, upload: Upload) -> Path:
    if upload.status != "completed":
        message = f"Results are not ready: the upload is {upload.status}"
        if upload.status == "failed" and upload.error:
            message += f" ({upload.error})"
        raise ResultsUnavailable(409, message)
    path = results_dir(settings, upload.id) / RESULTS_FILE
    if not path.exists():
        raise ResultsUnavailable(410, "The results of this upload are no longer available")
    return path


def layout(path: Path) -> Layout:
    names = pq.read_schema(path).names
    metadata = [c for c in METADATA_COLUMNS if c in names]
    fixed = {"row", LABEL_COLUMN, *PREDICTION_COLUMNS, *metadata}
    return Layout(metadata, LABEL_COLUMN in names, [c for c in names if c not in fixed])


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(config={"threads": 2, "memory_limit": "512MB"})


def _filters(decision: str | None, class_name: str | None) -> tuple[str, dict]:
    clauses, params = [], {}
    if decision is not None:
        clauses.append("decision = $decision")
        params["decision"] = decision
    if class_name is not None:
        clauses.append("class_name = $class_name")
        params["class_name"] = class_name
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def breakdown(path: Path, column: str, decision: str) -> dict[str, int]:
    """Flow counts per value of a column among flows with this decision, largest first."""
    assert column in SORTABLE
    with _connect() as con:
        rows = con.execute(f"SELECT {_q(column)}, count(*) FROM read_parquet($path) WHERE decision = $decision "
                           f"GROUP BY 1 ORDER BY 2 DESC, 1", {"path": str(path), "decision": decision}).fetchall()
    return {str(value): count for value, count in rows}


def _flow(record: dict, lay: Layout) -> dict:
    return {"row": record["row"],
            "metadata": {c: record[c] for c in lay.metadata},
            "label": record.get(LABEL_COLUMN),
            **{c: record[c] for c in PREDICTION_COLUMNS}}


def flows_page(path: Path, page: int, size: int, decision: str | None = None, class_name: str | None = None,
               sort: str = "row") -> tuple[list[dict], int]:
    """One page of flows (without the model input features) and the total matching the filters."""
    column, descending = sort.removeprefix("-"), sort.startswith("-")
    assert column in SORTABLE
    lay = layout(path)
    columns = lay.columns()
    where, params = _filters(decision, class_name)
    params["path"] = str(path)
    with _connect() as con:
        total = con.execute(f"SELECT count(*) FROM read_parquet($path){where}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT {', '.join(map(_q, columns))} FROM read_parquet($path){where} "
            f"ORDER BY {_q(column)} {'DESC' if descending else 'ASC'}, {_q('row')} LIMIT $limit OFFSET $offset",
            {**params, "limit": size, "offset": (page - 1) * size}).fetchall()
    return [_flow(dict(zip(columns, r)), lay) for r in rows], total


def flow_record(path: Path, row: int) -> dict | None:
    """Every stored column of one flow, model input features included."""
    with _connect() as con:
        cursor = con.execute(f"SELECT * FROM read_parquet($path) WHERE {_q('row')} = $row",
                             {"path": str(path), "row": row})
        values = cursor.fetchone()
        return None if values is None else dict(zip([d[0] for d in cursor.description], values))


def export_csv(path: Path, decision: str | None = None, class_name: str | None = None,
               features: bool = False) -> Iterator[bytes]:
    """The results as CSV, produced batch by batch so a large upload never sits in memory at once."""
    columns = layout(path).columns(features)
    where, params = _filters(decision, class_name)
    params["path"] = str(path)
    with _connect() as con:
        reader = con.sql(f"SELECT {', '.join(map(_q, columns))} FROM read_parquet($path){where} "
                         f"ORDER BY {_q('row')}", params=params).to_arrow_reader(EXPORT_BATCH_ROWS)
        header = True
        for batch in reader:
            buffer = io.BytesIO()
            pacsv.write_csv(pa.Table.from_batches([batch]), buffer,
                            write_options=pacsv.WriteOptions(include_header=header))
            header = False
            yield buffer.getvalue()
        if header:  # no matching flows: still a header row
            buffer = io.BytesIO()
            pacsv.write_csv(reader.schema.empty_table(), buffer)
            yield buffer.getvalue()
