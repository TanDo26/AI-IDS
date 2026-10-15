"""
What an uploaded file is, judged from its first bytes, never from its name or the client's Content-Type.

    pcap     a1b2c3d4 / d4c3b2a1 (µs), a1b23c4d / 4d3cb2a1 (ns)
    pcapng   0a0d0d0a
    csv      UTF-8 text whose first line is a header row
"""

import codecs
import csv

PCAP_MAGIC = {bytes.fromhex(m) for m in ("a1b2c3d4", "d4c3b2a1", "a1b23c4d", "4d3cb2a1")}
PCAPNG_MAGIC = bytes.fromhex("0a0d0d0a")
HEAD_BYTES = 64 * 1024        # enough for a CICFlowMeter header (~2 KB) and the first rows
UTF8_BOM = "﻿"


class UploadRejected(Exception):
    """Maps to an HTTP error: status, message and optional extra fields for the response body."""

    def __init__(self, status: int, message: str, **extra):
        self.status, self.message, self.extra = status, message, extra
        super().__init__(message)


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def csv_header(head: bytes, complete: bool) -> list[str]:
    """Column names from the first line of a UTF-8 CSV. complete: head is the whole file."""
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(head, final=complete)  # a cut character is fine
    except UnicodeDecodeError:
        raise UploadRejected(415, "Unsupported file type: not a pcap, pcapng or UTF-8 CSV file")
    if "\x00" in text:
        raise UploadRejected(415, "Unsupported file type: not a pcap, pcapng or UTF-8 CSV file")

    first_line, newline, rest = text.removeprefix(UTF8_BOM).partition("\n")
    if not newline and not complete:
        raise UploadRejected(415, f"No header row in the first {HEAD_BYTES // 1024} KB")
    columns = [c.strip() for c in next(csv.reader([first_line.rstrip("\r")]), [])]
    if len(columns) < 2 or any(not c for c in columns) or all(_is_number(c) for c in columns):
        raise UploadRejected(415, "Not a CSV with a header row (comma-separated column names on the first line)")
    if complete and not rest.strip():
        raise UploadRejected(422, "The CSV has a header row but no flows")
    return columns


def detect_file_type(head: bytes, complete: bool) -> tuple[str, list[str] | None]:
    """('pcap' | 'pcapng', None) or ('csv', column names); raises UploadRejected otherwise."""
    if not head:
        raise UploadRejected(422, "The file is empty")
    if head[:4] in PCAP_MAGIC:
        return "pcap", None
    if head[:4] == PCAPNG_MAGIC:
        return "pcapng", None
    return "csv", csv_header(head, complete)
