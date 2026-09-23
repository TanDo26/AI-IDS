"""
Model builders for the GeNIS IDS pipeline.
"""

from .logistic_regression import build_logistic_regression
from .random_forest import build_random_forest

MODEL_REGISTRY = {
    "logistic_regression": build_logistic_regression,
    "random_forest": build_random_forest,
    # Future:
    # "mlp": build_mlp,
    # "cnn": build_cnn,
    # "tabnet": build_tabnet,
    # "ft_transformer": build_ft_transformer,
}


def get_model(model_name: str, config: dict):
    """Instantiate a model by name from the registry."""
    if model_name not in MODEL_REGISTRY:
        available = ", ".join(MODEL_REGISTRY.keys())
        raise ValueError(f"Unknown model '{model_name}'. Available: {available}")
    return MODEL_REGISTRY[model_name](config)