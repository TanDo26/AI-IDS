"""
Sklearn-compatible wrapper for PyTorch models.
Provides fit(), predict(), predict_proba() so PyTorch models
integrate seamlessly with the existing pipeline.
"""

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.utils.class_weight import compute_class_weight
from tqdm import tqdm


class TorchClassifierWrapper:
    """Wraps a PyTorch nn.Module to behave like an sklearn estimator."""

    def __init__(
        self,
        model_factory,
        *,
        epochs=50,
        batch_size=1024,
        lr=1e-3,
        weight_decay=1e-4,
        patience=7,
        device=None,
        class_weight=None,
    ):
        self.model_factory = model_factory
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.weight_decay = weight_decay
        self.patience = patience
        self.class_weight = class_weight

        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model_ = None
        self.classes_ = None

    # ------------------------------------------------------------------
    # Sklearn-compatible API
    # ------------------------------------------------------------------
    def fit(self, X, y):
        X_np = self._to_numpy(X)
        y_np = self._to_numpy(y).astype(np.int64)

        self.classes_ = np.unique(y_np)
        n_classes = len(self.classes_)
        n_features = X_np.shape[1]

        # Build model
        self.model_ = self.model_factory(n_features, n_classes).to(self.device)

        # Loss with optional class weighting
        if self.class_weight == "balanced":
            weights = compute_class_weight(
                "balanced", classes=self.classes_, y=y_np
            )
            weight_tensor = torch.tensor(weights, dtype=torch.float32).to(self.device)
            criterion = nn.CrossEntropyLoss(weight=weight_tensor)
        else:
            criterion = nn.CrossEntropyLoss()

        optimizer = torch.optim.Adam(
            self.model_.parameters(),
            lr=self.lr,
            weight_decay=self.weight_decay,
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=3
        )

        # DataLoader
        X_t = torch.tensor(X_np, dtype=torch.float32)
        y_t = torch.tensor(y_np, dtype=torch.long)
        dataset = TensorDataset(X_t, y_t)
        loader = DataLoader(
            dataset, batch_size=self.batch_size, shuffle=True, drop_last=False
        )

        # Training loop with early stopping
        best_loss = float("inf")
        patience_counter = 0

        self.model_.train()
        epoch_bar = tqdm(
            range(self.epochs),
            desc="    Training",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
            ncols=80,
            leave=True,
        )
        for epoch in epoch_bar:
            epoch_loss = 0.0
            n_batches = 0

            batch_bar = tqdm(
                loader,
                desc=f"      Epoch {epoch+1:2d}",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
                ncols=80,
                leave=False,
            )
            for X_batch, y_batch in batch_bar:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                optimizer.zero_grad()
                logits = self.model_(X_batch)
                loss = criterion(logits, y_batch)
                loss.backward()
                optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1
                batch_bar.set_postfix_str(f"loss={loss.item():.4f}")
            batch_bar.close()

            avg_loss = epoch_loss / max(n_batches, 1)
            scheduler.step(avg_loss)

            current_lr = optimizer.param_groups[0]["lr"]
            epoch_bar.set_postfix_str(
                f"loss={avg_loss:.4f} best={best_loss:.4f} "
                f"p={patience_counter}/{self.patience} lr={current_lr:.1e}"
            )

            if avg_loss < best_loss - 1e-4:
                best_loss = avg_loss
                patience_counter = 0
                self._best_state = {
                    k: v.cpu().clone() for k, v in self.model_.state_dict().items()
                }
            else:
                patience_counter += 1

            if patience_counter >= self.patience:
                epoch_bar.set_postfix_str(f"Early stop @ epoch {epoch+1}")
                break
        epoch_bar.close()

        # Restore best weights
        if hasattr(self, "_best_state"):
            self.model_.load_state_dict(self._best_state)
            self.model_.to(self.device)

        return self

    def predict(self, X):
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]

    def predict_proba(self, X):
        X_np = self._to_numpy(X)
        X_t = torch.tensor(X_np, dtype=torch.float32)
        dataset = TensorDataset(X_t)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=False)

        self.model_.eval()
        all_probs = []
        with torch.no_grad():
            for (X_batch,) in loader:
                X_batch = X_batch.to(self.device)
                logits = self.model_(X_batch)
                probs = torch.softmax(logits, dim=1)
                all_probs.append(probs.cpu().numpy())

        return np.concatenate(all_probs, axis=0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_numpy(arr):
        if hasattr(arr, "values"):  # pandas
            return arr.values
        if hasattr(arr, "toarray"):  # sparse
            return arr.toarray()
        return np.asarray(arr)
