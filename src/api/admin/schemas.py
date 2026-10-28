"""
Request / response models for /admin.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from src.api.db.models import ModelVersion
from src.api.settings import get_settings
from src.api.uploads.schemas import UploadOut

Role = Literal["user", "admin"]


class ModelMetrics(BaseModel):
    """From the bundle's manifest: its test split at build time. None where the bundle has no value."""
    macro_f1: float | None = None                 # known classes
    attack_recall: float | None = None            # attack vs benign, classifier alone
    benign_fpr: float | None = None
    benign_as_unknown: float | None = None        # open-set false alarms on benign flows
    attack_as_unknown: float | None = None
    attack_missed: float | None = None
    latency_p50_ms: float | None = None           # one flow, CPU, end to end
    latency_p95_ms: float | None = None
    batch_flows_per_second: float | None = None

    @classmethod
    def from_manifest(cls, manifest: dict) -> "ModelMetrics":
        test = manifest.get("metrics", {}).get("test", {})
        mc, bv, os_ = test.get("multiclass", {}), test.get("attack_vs_benign", {}), test.get("open_set", {})
        latency = manifest.get("latency_cpu", {})
        return cls(macro_f1=mc.get("macro_f1"), attack_recall=bv.get("recall_attack"), benign_fpr=bv.get("fpr"),
                   benign_as_unknown=os_.get("benign_as_unknown"), attack_as_unknown=os_.get("attack_as_unknown"),
                   attack_missed=os_.get("attack_missed"), latency_p50_ms=latency.get("single_flow_ms_p50"),
                   latency_p95_ms=latency.get("single_flow_ms_p95"),
                   batch_flows_per_second=latency.get("batch_flows_per_second"))


class ModelVersionOut(BaseModel):
    id: int
    bundle_id: str
    status: str                                   # available | active | invalid | retired
    invalid_reason: str | None                    # also set on an active version that now fails its checks
    registered_at: datetime
    activated_at: datetime | None
    activated_by: int | None
    source: dict | None                           # experiment, model, strategy, split, feature selection
    classes: list[str]
    n_features: int | None
    metrics: ModelMetrics

    @classmethod
    def from_row(cls, row: ModelVersion) -> "ModelVersionOut":
        manifest = row.manifest or {}
        names = manifest.get("class_names", {})
        return cls(id=row.id, bundle_id=row.bundle_id, status=row.status, invalid_reason=row.invalid_reason,
                   registered_at=row.registered_at, activated_at=row.activated_at, activated_by=row.activated_by,
                   source=manifest.get("source"),
                   classes=[names.get(str(c), str(c)) for c in manifest.get("classes", [])],
                   n_features=len(manifest["required_features"]) if "required_features" in manifest else None,
                   metrics=ModelMetrics.from_manifest(manifest))


class LoadedModel(BaseModel):
    loaded: str | None                            # bundle id in memory
    loaded_at: str | None
    active_in_store: str | None                   # what the database says is active
    last_error: str | None                        # the last bundle that failed to load


class ProcessModel(LoadedModel):
    process: str                                  # host:pid
    kind: str                                     # api | worker
    reported_at: str
    lagging: bool                                 # has something other than the active version loaded


class ModelsOverview(BaseModel):
    active: str | None
    versions: list[ModelVersionOut]
    this_process: LoadedModel                     # the API process that answered this request
    processes: list[ProcessModel] | None          # every process reporting via Redis; None without Redis


class RescanOut(BaseModel):
    added: list[str]
    verified: list[str]
    invalid: list[str]
    retired: list[str]
    versions: list[ModelVersionOut]


class ActivationOut(BaseModel):
    version: ModelVersionOut
    previous: str | None
    changed: bool                                 # False if the version was already active
    notified: bool                                # processes told via Redis; otherwise they switch at their next poll


# ── users ───────────────────────────────────────────────────

class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    email_verified_at: datetime | None

    @computed_field
    @property
    def needs_email_verification(self) -> bool:
        """The user can't use the app until they confirm their address (IDS_EMAIL_VERIFICATION)."""
        return get_settings().email_verification and self.email_verified_at is None


class UserPage(BaseModel):
    items: list[UserAdminOut]
    total: int
    page: int
    size: int


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: Role | None = None

    @model_validator(mode="after")
    def _something(self):
        if self.is_active is None and self.role is None:
            raise ValueError("Send is_active and/or role")
        return self


# ── usage ───────────────────────────────────────────────────

class UsageRow(BaseModel):
    user_id: int
    email: str
    username: str
    role: Role
    is_active: bool
    uploads: int                    # in the period, deleted ones included
    failed_uploads: int
    deleted_uploads: int
    bytes: int                      # uploaded
    flows: int                      # processed
    processing_ms: int
    storage_bytes: int              # held right now: raw files not purged or deleted + result files


class UsageOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: date | None = Field(alias="from")
    to: date | None
    users: list[UsageRow]           # every user, most bytes first
    totals: dict[str, int]          # uploads, failed_uploads, deleted_uploads, bytes, flows, processing_ms, storage_bytes


class DailyUsage(BaseModel):
    day: date                       # UTC
    uploads: int
    bytes: int
    flows: int
    processing_ms: int


class DailyUsageOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int
    from_: date = Field(alias="from")
    to: date
    days: list[DailyUsage]          # every day in the range, zero-filled


# ── uploads and audit ───────────────────────────────────────

class AdminUploadOut(UploadOut):
    owner_email: str
    owner_username: str
    deleted_at: datetime | None


class AdminUploadPage(BaseModel):
    items: list[AdminUploadOut]
    total: int
    page: int
    size: int


class AuditOut(BaseModel):
    id: int
    actor_id: int | None            # None: a CLI script, or a deleted user
    actor_email: str | None
    action: str
    target_type: str
    target_id: str
    details: dict
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    size: int


# ── server status ───────────────────────────────────────────

class GpuStats(BaseModel):
    name: str
    utilization_percent: float
    memory_used_mb: int
    memory_total_mb: int


class SystemStats(BaseModel):
    cpu_percent: float
    ram_percent: float
    ram_used_mb: int
    ram_total_mb: int
    disk_percent: float                     # the data volume (uploads + results)
    disk_free_gb: float
    disk_total_gb: float
    disk_warning: bool                      # at or above IDS_DISK_WARNING_PERCENT
    gpus: list[GpuStats]                    # empty without a visible NVIDIA GPU


class Check(BaseModel):
    ok: bool
    error: str | None = None


class QueueStatus(Check):
    queued: int | None = None               # waiting in Redis
    unacknowledged: int | None = None       # delivered to a worker, not finished (running or reserved)
    workers: list[str] | None = None        # Celery workers that answered a ping


class UploadStats(BaseModel):
    by_status: dict[str, int]               # uploads not deleted
    failed_last_24h: int
    stuck: int                              # converting/predicting for over 35 minutes


class ModelStatus(LoadedModel):
    lagging_processes: int | None           # processes reporting a non-active bundle; None without Redis


class ApiStatus(BaseModel):
    version: str
    process: str                            # host:pid of the API process that answered
    started_at: datetime
    uptime_s: int


class ServerStatus(BaseModel):
    checked_at: datetime
    api: ApiStatus
    system: SystemStats
    database: Check
    redis: Check
    queue: QueueStatus
    uploads: UploadStats | None             # None when the database is unreachable
    model: ModelStatus
    warnings: list[str]                     # plain-language problems, most urgent first
