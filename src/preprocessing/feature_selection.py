import numpy as np
import pandas as pd


class FeatureSelector:

    def __init__(
        self,
        drop_zero_variance=True,
        drop_high_correlation=True,
        correlation_threshold=0.95,
    ):
        self.drop_zero_variance = drop_zero_variance
        self.drop_high_correlation = drop_high_correlation
        self.correlation_threshold = correlation_threshold

        self.selected_columns_ = None
        self.dropped_zero_var_ = []
        self.dropped_corr_ = []

    def fit(self, X_train: pd.DataFrame):

        cols_to_keep = list(X_train.columns)

        if self.drop_zero_variance:
            variances = X_train[cols_to_keep].var()

            zero_var = variances[variances == 0].index.tolist()

            self.dropped_zero_var_ = zero_var

            cols_to_keep = [c for c in cols_to_keep if c not in zero_var]

        if (self.drop_high_correlation and len(cols_to_keep) > 1):
            corr_matrix = X_train[cols_to_keep].corr().abs()

            upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))

            to_drop = [col for col in upper.columns if any(upper[col] > self.correlation_threshold)]

            self.dropped_corr_ = to_drop

            cols_to_keep = [c for c in cols_to_keep if c not in to_drop]

        self.selected_columns_ = cols_to_keep

        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:

        if self.selected_columns_ is None:
            raise RuntimeError("FeatureSelector has not been fitted.")

        return X[self.selected_columns_].copy()

    def fit_transform(self, X_train):
        return self.fit(X_train).transform(X_train)

    def summary(self) -> str:
        lines = [
            f"Selected features: "
            f"{len(self.selected_columns_)}",

            f"Dropped (zero-variance): "
            f"{len(self.dropped_zero_var_)} "
            f"— {self.dropped_zero_var_}",

            f"Dropped (high corr): "
            f"{len(self.dropped_corr_)} "
            f"— {self.dropped_corr_}",
        ]

        return "\n".join(lines)