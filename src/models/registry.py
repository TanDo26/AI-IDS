from .logistic_regression import build_logistic_regression
from .random_forest import build_random_forest

MODEL_REGISTRY = {
    "logistic_regression": build_logistic_regression,
    "random_forest": build_random_forest
}


def get_model(model_name: str, config: dict):
    if model_name not in MODEL_REGISTRY:
        available = ", ".join(MODEL_REGISTRY.keys())
        raise ValueError(f"Unknown model '{model_name}'. Available: {available}")
    return MODEL_REGISTRY[model_name](config)