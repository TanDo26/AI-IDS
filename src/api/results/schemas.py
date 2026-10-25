"""
Response models for an upload's results.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["benign", "known_attack", "unknown"]


class ModelRef(BaseModel):
    version_id: int | None
    bundle_id: str | None
    experiment: str | None
    model: str | None


class SummaryOut(BaseModel):
    upload_id: uuid.UUID
    n_flows: int
    n_benign: int
    n_known_attack: int
    n_unknown: int
    attack_breakdown: dict[str, int]        # known attacks per class name
    unknown_breakdown: dict[str, int]       # unknown flows per reason: low_confidence | anomalous
    label_agreement: float | None           # attack-vs-benign agreement with the uploaded Label column
    inference_ms: float
    processing_ms: int | None
    model: ModelRef


class FlowOut(BaseModel):
    row: int
    metadata: dict[str, str | None]         # Flow ID, Src/Dst IP and port, Timestamp: those uploaded
    label: str | None                       # the uploaded Label, if any
    decision: Decision
    reason: str                             # benign | known | low_confidence | anomalous
    predicted_class: int
    class_name: str
    confidence: float
    attack_score: float
    anomaly_score: float
    imputed_cells: int


class FlowPage(BaseModel):
    items: list[FlowOut]
    total: int
    page: int
    size: int


class Contribution(BaseModel):
    feature: str
    value: float | None                     # None: the uploaded value was missing and imputed
    contribution: float
    benign_median: float | None = None      # anomaly explanations only
    deviation_sd: float | None = None


class Explanation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target: Literal["class", "anomaly"]
    class_: int | None = Field(None, alias="class")
    class_name: str | None = None
    output_space: str                       # probability | log_odds | anomaly_score
    base_value: float
    contributions: list[Contribution]


class ExplanationOut(BaseModel):
    upload_id: uuid.UUID
    row: int
    bundle_id: str                          # the bundle that produced this result
    decision: Decision
    reason: str
    predicted_class: int
    class_name: str
    confidence: float
    attack_score: float
    anomaly_score: float
    explanations: list[Explanation]         # two for low_confidence (the top two classes)
