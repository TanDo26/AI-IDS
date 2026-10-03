"""
AI-IDS Inference API — FastAPI deployment.
Loads a trained model + preprocessor and exposes /predict and /batch_predict endpoints.
"""

import os
import sys
import time
import json
from pathlib import Path
from contextlib import asynccontextmanager

import yaml
import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────

class PredictRequest(BaseModel):
    features: dict

class BatchPredictRequest(BaseModel):
    flows: list[dict]

class PredictResponse(BaseModel):
    prediction: str
    prediction_code: int
    probabilities: list[float] | None = None
    inference_time_ms: float

class BatchPredictResponse(BaseModel):
    predictions: list[PredictResponse]
    total_flows: int
    total_inference_time_ms: float


# ──────────────────────────────────────────────
# Global state
# ──────────────────────────────────────────────

class SystemState:
    """Holds loaded model, preprocessor, and metadata."""
    def __init__(self):
        self.config = None
        self.model = None
        self.feature_selector = None
        self.preprocessor = None
        self.selected_features: list[str] = []
        self.label_mapping: dict | None = None  # int → label name
        self.label_type: str = "binary"
        self.is_loaded: bool = False

state = SystemState()


def load_system():
    """Load model, preprocessor, and label mapping from disk."""
    # Configurable via environment variables
    exp_name = os.environ.get("IDS_EXP_NAME", "EXP-02")
    model_type = os.environ.get("IDS_MODEL_TYPE", "random_forest")
    split_name = os.environ.get("IDS_SPLIT", "random")
    state.label_type = os.environ.get("IDS_LABEL_TYPE", "binary")

    config_path = PROJECT_ROOT / "configs" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        state.config = yaml.safe_load(f)

    # Paths
    models_dir = PROJECT_ROOT / state.config["output"]["models_dir"] / split_name
    preproc_dir = PROJECT_ROOT / state.config["output"]["preprocessors_dir"]

    # Determine model file extension
    is_torch = model_type in ("mlp", "lstm")
    ext = ".pt" if is_torch else ".pkl"
    model_path = models_dir / f"{exp_name}_{model_type}{ext}"
    selector_path = preproc_dir / f"{split_name}_feature_selector.pkl"
    preprocessor_path = preproc_dir / f"{split_name}_preprocessor.pkl"

    for path in [model_path, selector_path, preprocessor_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {path}")

    print(f"  Loading model: {model_path.name}")
    if is_torch:
        import torch
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        state.model = torch.load(model_path, map_location=device, weights_only=False)
    else:
        state.model = joblib.load(model_path)

    state.feature_selector = joblib.load(selector_path)
    state.preprocessor = joblib.load(preprocessor_path)
    state.selected_features = state.feature_selector.selected_columns_

    # Load label mapping for multiclass
    ds_name = state.config["active_dataset"]
    mapping_path = Path(state.config["datasets"][ds_name]["data_dir"]) / "label_mapping.json"
    if mapping_path.exists():
        with open(mapping_path, "r", encoding="utf-8") as f:
            mapping_data = json.load(f)
            state.label_mapping = mapping_data.get("int_to_label")

    state.is_loaded = True
    print(f"  ✅ System ready | Model: {exp_name} | Type: {model_type} | Label: {state.label_type}")


def _predict_label(code: int) -> str:
    """Convert prediction code to human-readable label."""
    if state.label_type == "binary":
        return "Attack" if code == 1 else "Benign"
    else:
        if state.label_mapping and str(code) in state.label_mapping:
            return state.label_mapping[str(code)]
        return f"Class_{code}"


def _run_inference(df_input: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None, float]:
    """Run the full inference pipeline on a DataFrame. Returns (predictions, probabilities, time_ms)."""
    # Ensure all required features exist
    for col in state.selected_features:
        if col not in df_input.columns:
            df_input[col] = 0.0

    df_input = df_input[state.selected_features]
    X_t = state.preprocessor.transform(df_input)

    start = time.perf_counter()
    predictions = state.model.predict(X_t)
    elapsed_ms = (time.perf_counter() - start) * 1000

    probabilities = None
    if hasattr(state.model, "predict_proba"):
        probabilities = state.model.predict_proba(X_t)

    return predictions, probabilities, elapsed_ms


# ──────────────────────────────────────────────
# App setup with lifespan
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("=" * 50)
    print("  AI-IDS Inference API — Starting up")
    print("=" * 50)
    load_system()
    yield
    # Shutdown
    print("  AI-IDS API shutting down.")

app = FastAPI(
    title="AI-IDS Inference API",
    description="Real-time network intrusion detection using trained ML models.",
    version="2.0.0",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.get("/")
def read_root():
    return {
        "service": "AI-IDS Inference API",
        "version": "2.0.0",
        "endpoints": ["/predict", "/batch_predict", "/health"],
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy" if state.is_loaded else "not_ready",
        "model_loaded": state.is_loaded,
        "label_type": state.label_type,
        "n_features": len(state.selected_features),
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if not state.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    try:
        df_input = pd.DataFrame([req.features])
        predictions, probabilities, elapsed_ms = _run_inference(df_input)

        code = int(predictions[0])
        proba = probabilities[0].tolist() if probabilities is not None else None

        return PredictResponse(
            prediction=_predict_label(code),
            prediction_code=code,
            probabilities=proba,
            inference_time_ms=round(elapsed_ms, 3),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid input data: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.post("/batch_predict", response_model=BatchPredictResponse)
def batch_predict(req: BatchPredictRequest):
    if not state.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    if not req.flows:
        raise HTTPException(status_code=422, detail="Empty flows list.")

    try:
        df_input = pd.DataFrame(req.flows)
        predictions, probabilities, elapsed_ms = _run_inference(df_input)

        results = []
        for i in range(len(predictions)):
            code = int(predictions[i])
            proba = probabilities[i].tolist() if probabilities is not None else None
            results.append(PredictResponse(
                prediction=_predict_label(code),
                prediction_code=code,
                probabilities=proba,
                inference_time_ms=round(elapsed_ms / len(predictions), 3),
            ))

        return BatchPredictResponse(
            predictions=results,
            total_flows=len(predictions),
            total_inference_time_ms=round(elapsed_ms, 3),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
