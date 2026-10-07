import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif, r_regression
from sklearn.model_selection import train_test_split

SUPERVISED_METHODS = ("pearson", "mutual_info")


class FeatureSelector:

    def __init__(
        self,
        drop_zero_variance=True,
        drop_high_correlation=True,
        correlation_threshold=0.95,
        method="none",
        threshold=None,
        top_k=None,
        sample_size=None,
        random_state=42,
    ):
        if method not in ("none",) + SUPERVISED_METHODS:
            raise ValueError(f"Unknown feature selection method '{method}'. "
                             f"Available: none, {', '.join(SUPERVISED_METHODS)}")
        if method != "none" and top_k is None and threshold is None:
            raise ValueError(f"Feature selection method '{method}' needs top_k or threshold.")

        self.drop_zero_variance = drop_zero_variance
        self.drop_high_correlation = drop_high_correlation
        self.correlation_threshold = correlation_threshold
        self.method = method
        self.threshold = threshold
        self.top_k = top_k
        self.sample_size = sample_size
        self.random_state = random_state

        self.selected_columns_ = None
        self.dropped_zero_var_ = []
        self.dropped_corr_ = []
        self.dropped_supervised_ = []
        self.scores_ = {}

    def fit(self, X_train: pd.DataFrame, y_train=None):

        if self.method != "none" and y_train is None:
            raise ValueError(f"Feature selection method '{self.method}' needs y_train.")

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

        # Supervised ranking on the columns that survived the base filters
        if self.method != "none":
            if self.method == "pearson":
                scores = self._pearson_scores(X_train[cols_to_keep], y_train)
            else:
                scores = self._mutual_info_scores(X_train[cols_to_keep], y_train)

            self.scores_ = dict(zip(cols_to_keep, scores.tolist()))
            kept = self._select_by_score(cols_to_keep, scores)

            self.dropped_supervised_ = [c for c in cols_to_keep if c not in kept]
            cols_to_keep = kept

        self.selected_columns_ = cols_to_keep

        return self

    def _pearson_scores(self, X: pd.DataFrame, y) -> np.ndarray:
        """|Pearson r| with the target; multiclass uses one-vs-rest and keeps the max per feature."""
        X_arr = X.to_numpy(dtype=np.float64)
        y_arr = np.asarray(y)
        classes = np.unique(y_arr)
        # Binary: one indicator is enough, |r| is the same for both classes
        targets = classes[1:] if len(classes) == 2 else classes

        scores = np.zeros(X_arr.shape[1])
        for c in targets:
            r = r_regression(X_arr, (y_arr == c).astype(np.float64))
            scores = np.maximum(scores, np.abs(r))
        return scores

    def _mutual_info_scores(self, X: pd.DataFrame, y) -> np.ndarray:
        """Mutual information with the target, scored on a stratified subsample (kNN estimator is slow)."""
        y_arr = np.asarray(y)
        if self.sample_size and len(X) > self.sample_size:
            X, _, y_arr, _ = train_test_split(
                X, y_arr,
                train_size=self.sample_size,
                stratify=y_arr,
                random_state=self.random_state,
            )
        return mutual_info_classif(X, y_arr, random_state=self.random_state, n_jobs=-1)

    def _select_by_score(self, cols, scores) -> list:
        order = np.argsort(-scores, kind="stable")
        if self.top_k is not None:
            keep_idx = order[:self.top_k]
        else:
            keep_idx = [i for i in order if scores[i] >= self.threshold]

        if len(keep_idx) == 0:
            raise ValueError(f"Feature selection '{self.method}' kept no features "
                             f"(threshold={self.threshold}, top_k={self.top_k}).")

        keep = {cols[i] for i in keep_idx}
        return [c for c in cols if c in keep]  # keep the original column order

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:

        if self.selected_columns_ is None:
            raise RuntimeError("FeatureSelector has not been fitted.")

        return X[self.selected_columns_].copy()

    def fit_transform(self, X_train, y_train=None):
        return self.fit(X_train, y_train).transform(X_train)

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

        # getattr: selectors pickled before supervised methods existed lack these attributes
        method = getattr(self, "method", "none")
        if method != "none":
            dropped = self.dropped_supervised_
            top = sorted(self.scores_.items(), key=lambda kv: kv[1], reverse=True)[:10]
            lines += [
                f"Dropped ({method}): {len(dropped)} — {dropped}",
                f"Top {method} scores: " + ", ".join(f"{c}={s:.4f}" for c, s in top),
            ]

        return "\n".join(lines)


def build_feature_selector(config: dict, fs_profile: str = "none") -> FeatureSelector:
    """Build a FeatureSelector from the base filters + a named feature-selection profile."""
    pp_cfg = config["preprocessing"]
    fs_cfg = pp_cfg["feature_selection"]
    profiles = pp_cfg.get("feature_selection_profiles", {"none": {"method": "none"}})

    if fs_profile not in profiles:
        available = ", ".join(profiles)
        raise ValueError(f"Unknown feature_selection profile '{fs_profile}'. Available: {available}")

    profile = profiles[fs_profile]
    return FeatureSelector(
        drop_zero_variance=fs_cfg["drop_zero_variance"],
        drop_high_correlation=fs_cfg["drop_high_correlation"],
        correlation_threshold=fs_cfg["correlation_threshold"],
        method=profile.get("method", "none"),
        threshold=profile.get("threshold"),
        top_k=profile.get("top_k"),
        sample_size=profile.get("sample_size"),
        random_state=profile.get("random_state", 42),
    )
