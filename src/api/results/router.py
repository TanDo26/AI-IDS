"""
An upload's results: summary, paginated flows, per-flow explanations, CSV export (owner or admin).
"""

import pathlib
import re
import uuid

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.auth.deps import get_current_user
from src.api.db.models import ModelVersion, Upload, User
from src.api.db.session import get_db
from src.api.results import service
from src.api.results.schemas import Decision, ExplanationOut, FlowPage, ModelRef, SummaryOut
from src.api.settings import get_settings
from src.api.uploads import service as uploads
from src.api.uploads.validation import UploadRejected
from src.inference.bundle import BundleError

router = APIRouter(prefix="/uploads", tags=["results"])

SORT_PATTERN = "^-?(" + "|".join(service.SORTABLE) + ")$"
STORED_PREDICTION = ("decision", "reason", "predicted_class", "confidence", "attack_score", "anomaly_score")


def _completed(db: Session, upload_id: uuid.UUID, user: User) -> tuple[Upload, pathlib.Path]:
    """The upload (404 unless owner/admin) and its results file (409 not ready, 410 gone)."""
    try:
        upload = uploads.get_upload(db, upload_id, user)
        return upload, service.results_file(get_settings(), upload)
    except UploadRejected as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except service.ResultsUnavailable as e:
        raise HTTPException(status_code=e.status, detail=e.message)


def _version(db: Session, upload: Upload) -> ModelVersion | None:
    return db.get(ModelVersion, upload.model_version_id) if upload.model_version_id is not None else None


@router.get("/{upload_id}/summary", response_model=SummaryOut)
def summary(upload_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Decision counts, known attacks per type, unknowns per reason, and the model that produced them."""
    upload, path = _completed(db, upload_id, user)
    s, version = upload.summary, _version(db, upload)
    source = (version.manifest or {}).get("source", {}) if version else {}
    return SummaryOut(
        upload_id=upload.id, n_flows=upload.n_flows, n_benign=s.n_benign, n_known_attack=s.n_known_attack,
        n_unknown=s.n_unknown, attack_breakdown=s.attack_breakdown,
        unknown_breakdown=service.breakdown(path, "reason", decision="unknown"),
        label_agreement=s.label_agreement, inference_ms=s.inference_ms, processing_ms=upload.processing_ms,
        capture=s.capture,
        model=ModelRef(version_id=upload.model_version_id, bundle_id=version.bundle_id if version else None,
                       experiment=source.get("experiment"), model=source.get("model")))


@router.get("/{upload_id}/flows", response_model=FlowPage)
def flows(upload_id: uuid.UUID, page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
          decision: Decision | None = None, class_name: str | None = Query(None, max_length=128),
          sort: str = Query("row", pattern=SORT_PATTERN, description="A column, '-' first for descending"),
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One page of flows with their predictions, optionally filtered by decision and/or class."""
    _, path = _completed(db, upload_id, user)
    items, total = service.flows_page(path, page, size, decision, class_name, sort)
    return FlowPage(items=items, total=total, page=page, size=size)


@router.get("/{upload_id}/flows/{row}/explain", response_model=ExplanationOut)
def explain(request: Request, upload_id: uuid.UUID, row: int = Path(ge=0),
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Which features drove this flow's decision, computed with the bundle that produced it."""
    upload, path = _completed(db, upload_id, user)
    version = _version(db, upload)
    if version is None:
        raise HTTPException(status_code=410, detail="The model version that produced these results is no longer registered")
    record = service.flow_record(path, row)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No flow {row} in this upload")
    try:
        explainer = request.app.state.explainers.get(version.bundle_id)
    except BundleError as e:
        raise HTTPException(status_code=410, detail=f"The model that produced these results ({version.bundle_id}) "
                                                    f"can no longer be loaded: {e}")
    if any(f not in record for f in explainer.features):
        raise HTTPException(status_code=410, detail="These results don't contain the model's input features")

    flow = pd.DataFrame([{f: record[f] for f in explainer.features}], dtype=float)   # None -> NaN (imputed)
    stored = pd.Series({k: record[k] for k in STORED_PREDICTION})                  # explain what was recorded
    return {**explainer.explain(flow, result=stored), "upload_id": upload.id, "row": row}


def _download_name(upload: Upload) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pathlib.PurePath(upload.original_filename).stem).strip("._") or "upload"
    return f"{stem[:100]}-results.csv"


@router.get("/{upload_id}/export.csv")
def export_csv(upload_id: uuid.UUID, decision: Decision | None = None,
               class_name: str | None = Query(None, max_length=128),
               features: bool = Query(False, description="Also include the model input features"),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Download the results as CSV: row, metadata, Label, predictions (and optionally features)."""
    upload, path = _completed(db, upload_id, user)
    return StreamingResponse(service.export_csv(path, decision, class_name, features), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{_download_name(upload)}"'})
