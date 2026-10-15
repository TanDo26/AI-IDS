"""
Response models for /uploads.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

UploadStatus = Literal["queued", "converting", "predicting", "completed", "failed"]


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: int
    original_filename: str          # as sent by the client, for display only
    file_type: str                  # csv | pcap | pcapng, from the file's content
    size_bytes: int
    sha256: str
    status: UploadStatus
    progress: int                   # 0-100
    error: str | None
    n_flows: int | None
    model_version_id: int | None    # the model version that produced the results
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    processing_ms: int | None
    raw_deleted_at: datetime | None  # the raw file was removed by retention; results remain


class UploadPage(BaseModel):
    items: list[UploadOut]
    total: int
    page: int
    size: int
