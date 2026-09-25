"""
MLP (Multi-Layer Perceptron) model builder using PyTorch.
"""

import torch.nn as nn
from functools import partial
from .torch_wrapper import TorchClassifierWrapper


class MLPNetwork(nn.Module):
    """A 3-layer MLP with BatchNorm, ReLU activations, and Dropout."""

    def __init__(self, n_features, n_classes, hidden_sizes=None, dropout=0.3):
        super().__init__()
        if hidden_sizes is None:
            hidden_sizes = [256, 128, 64]

        layers = []
        in_dim = n_features
        for h in hidden_sizes:
            layers.extend([
                nn.Linear(in_dim, h),
                nn.BatchNorm1d(h),
                nn.ReLU(),
                nn.Dropout(dropout),
            ])
            in_dim = h
        layers.append(nn.Linear(in_dim, n_classes))

        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def build_mlp(config, model_name="mlp", class_weight=None):
    """Build an MLP classifier wrapped in sklearn-compatible API."""
    mlp_cfg = config["models"].get(model_name, config["models"].get("mlp", {}))

    hidden_sizes = mlp_cfg.get("hidden_sizes", [256, 128, 64])
    dropout = mlp_cfg.get("dropout", 0.3)

    factory = partial(MLPNetwork, hidden_sizes=hidden_sizes, dropout=dropout)

    return TorchClassifierWrapper(
        model_factory=factory,
        epochs=mlp_cfg.get("epochs", 50),
        batch_size=mlp_cfg.get("batch_size", 1024),
        lr=mlp_cfg.get("lr", 1e-3),
        weight_decay=mlp_cfg.get("weight_decay", 1e-4),
        patience=mlp_cfg.get("patience", 7),
        class_weight=class_weight,
    )
