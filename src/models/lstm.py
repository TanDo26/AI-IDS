"""
LSTM model builder using PyTorch.
Input features are reshaped to (batch, 1, n_features) — treating
each sample as a single-timestep sequence.
"""

import torch.nn as nn
from functools import partial
from .torch_wrapper import TorchClassifierWrapper


class LSTMNetwork(nn.Module):

    def __init__(self, n_features, n_classes, hidden_size=128,
                 num_layers=2, dropout=0.3, bidirectional=False):
        super().__init__()
        self.n_features = n_features

        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=bidirectional,
        )

        fc_input = hidden_size * (2 if bidirectional else 1)
        self.head = nn.Sequential(
            nn.BatchNorm1d(fc_input),
            nn.Dropout(dropout),
            nn.Linear(fc_input, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, n_classes),
        )

    def forward(self, x):
        # x shape: (batch, n_features) → (batch, 1, n_features)
        if x.dim() == 2:
            x = x.unsqueeze(1)
        # lstm_out: (batch, seq_len, hidden*dirs)
        lstm_out, _ = self.lstm(x)
        # Take the last timestep
        last_hidden = lstm_out[:, -1, :]
        return self.head(last_hidden)


def build_lstm(config, model_name="lstm", class_weight=None):
    lstm_cfg = config["models"].get(model_name, config["models"].get("lstm", {}))

    hidden_size = lstm_cfg.get("hidden_size", 128)
    num_layers = lstm_cfg.get("num_layers", 2)
    dropout = lstm_cfg.get("dropout", 0.3)
    bidirectional = lstm_cfg.get("bidirectional", False)

    factory = partial(
        LSTMNetwork,
        hidden_size=hidden_size,
        num_layers=num_layers,
        dropout=dropout,
        bidirectional=bidirectional,
    )

    return TorchClassifierWrapper(
        model_factory=factory,
        epochs=lstm_cfg.get("epochs", 50),
        batch_size=lstm_cfg.get("batch_size", 1024),
        lr=lstm_cfg.get("lr", 1e-3),
        weight_decay=lstm_cfg.get("weight_decay", 1e-4),
        patience=lstm_cfg.get("patience", 7),
        class_weight=class_weight,
    )
