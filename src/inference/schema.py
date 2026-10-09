"""
Column names accepted for uploaded flows.
"""

import pandas as pd

JAVA_TO_TRAINING = {
    "Total Fwd Packet": "Total Fwd Packets",
    "Total Bwd packets": "Total Backward Packets",
    "Total Length of Fwd Packet": "Fwd Packets Length Total",
    "Total Length of Bwd Packet": "Bwd Packets Length Total",
    "Average Packet Size": "Avg Packet Size",
    "Fwd Segment Size Avg": "Avg Fwd Segment Size",
    "Bwd Segment Size Avg": "Avg Bwd Segment Size",
    "Fwd Bytes/Bulk Avg": "Fwd Avg Bytes/Bulk",
    "Fwd Packet/Bulk Avg": "Fwd Avg Packets/Bulk",
    "Fwd Bulk Rate Avg": "Fwd Avg Bulk Rate",
    "Bwd Bytes/Bulk Avg": "Bwd Avg Bytes/Bulk",
    "Bwd Packet/Bulk Avg": "Bwd Avg Packets/Bulk",
    "Bwd Bulk Rate Avg": "Bwd Avg Bulk Rate",
    "FWD Init Win Bytes": "Init Fwd Win Bytes",
    "Bwd Init Win Bytes": "Init Bwd Win Bytes",
    "Fwd Act Data Pkts": "Fwd Act Data Packets",
}

METADATA_COLUMNS = ("Flow ID", "Src IP", "Src Port", "Dst IP", "Dst Port", "Timestamp")
LABEL_COLUMN = "Label"


def _key(name) -> str:
    return " ".join(str(name).split()).lower()


def normalize_columns(df: pd.DataFrame, feature_names) -> tuple[pd.DataFrame, dict]:
    """Rename uploaded columns to training names. Returns (renamed df, {original: new})."""
    canonical = {_key(n): n for n in (*feature_names, *METADATA_COLUMNS, LABEL_COLUMN)}
    canonical.update({_key(java): train for java, train in JAVA_TO_TRAINING.items()})

    taken = {col for col in df.columns if canonical.get(_key(col)) == col}
    renames = {}
    for col in df.columns:
        target = canonical.get(_key(col))
        if target is not None and target != col and target not in taken:
            taken.add(target)
            renames[col] = target
    return df.rename(columns=renames), renames
