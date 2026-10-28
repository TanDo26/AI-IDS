"""
JSON inference for scripts: POST /predict (one flow) and /batch_predict (up to 10k flows).
"""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import pandas as pd

from src.api.auth.deps import get_verified_user
from src.api.runtime.model_manager import require_engine
from src.inference.engine import InferenceEngine, MissingFeaturesError

MAX_BATCH = 10_000

# Any logged-in user; scripts send `Authorization: Bearer <access_token from /auth/login>`
router = APIRouter(tags=["inference"], dependencies=[Depends(get_verified_user)])


class PredictRequest(BaseModel):
    features: dict[str, Any]


class BatchPredictRequest(BaseModel):
    flows: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_BATCH)


class FlowPrediction(BaseModel):
    decision: str            # benign | known_attack | unknown
    reason: str              # benign | known | low_confidence | anomalous
    predicted_class: int
    class_name: str
    confidence: float
    attack_score: float      # 1 - P(Benign)
    anomaly_score: float
    imputed_cells: int       # inputs that were missing / inf / non-numeric and got imputed


class PredictResponse(FlowPrediction):
    bundle_id: str
    inference_ms: float


class BatchPredictResponse(BaseModel):
    bundle_id: str
    total_flows: int
    inference_ms: float
    predictions: list[FlowPrediction]


def _predict(engine: InferenceEngine, flows: list[dict]) -> tuple[list[FlowPrediction], float]:
    start = time.perf_counter()
    try:
        result = engine.predict(pd.DataFrame(flows))
    except MissingFeaturesError as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "missing": e.missing})
    elapsed_ms = (time.perf_counter() - start) * 1000
    fields = list(FlowPrediction.model_fields)
    return [FlowPrediction(**row) for row in result[fields].to_dict(orient="records")], elapsed_ms


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, engine: InferenceEngine = Depends(require_engine)):
    [prediction], elapsed_ms = _predict(engine, [req.features])
    return PredictResponse(**prediction.model_dump(), bundle_id=engine.bundle.bundle_id,
                           inference_ms=round(elapsed_ms, 3))


@router.post("/batch_predict", response_model=BatchPredictResponse)
def batch_predict(req: BatchPredictRequest, engine: InferenceEngine = Depends(require_engine)):
    predictions, elapsed_ms = _predict(engine, req.flows)
    return BatchPredictResponse(bundle_id=engine.bundle.bundle_id, total_flows=len(predictions),
                                inference_ms=round(elapsed_ms, 3), predictions=predictions)
