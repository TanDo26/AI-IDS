"""
Inference engine: uploaded flows -> per-flow decisions with the active bundle.

"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .schema import normalize_columns, METADATA_COLUMNS, LABEL_COLUMN

BATCH_SIZE = 50_000


class MissingFeaturesError(ValueError):

    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__(f"{len(self.missing)} required feature(s) missing: {', '.join(self.missing)}")


@dataclass
class PreparedFlows:
    features: pd.DataFrame        # required features only, numeric, NaN where values were unusable
    metadata: pd.DataFrame        # Flow ID / IPs / ports / timestamp, when present
    label: pd.Series | None       # uploaded ground-truth label, when present
    imputed_cells: np.ndarray     # per flow: required-feature values that will be imputed
    renamed: dict                 # uploaded column -> training name


class InferenceEngine:

    def __init__(self, bundle, batch_size=BATCH_SIZE):
        self.bundle = bundle
        self.batch_size = batch_size
        self.required = list(bundle.manifest["required_features"])
        self.class_names = bundle.manifest["class_names"]

    def missing_features(self, columns) -> list[str]:
        """Required features absent from these column names, after the same renaming as prepare()."""
        df, _ = normalize_columns(pd.DataFrame(columns=list(columns)), self.required)
        return [f for f in self.required if f not in df.columns]

    def prepare(self, df: pd.DataFrame) -> PreparedFlows:
        df, renamed = normalize_columns(df, self.required)
        missing = [f for f in self.required if f not in df.columns]
        if missing:
            raise MissingFeaturesError(missing)

        features = df[self.required]
        # Text columns: numbers or NaN. Only those, since pandas' per-column work costs ~0.5 ms a column
        text = [c for c, dtype in features.dtypes.items() if not pd.api.types.is_numeric_dtype(dtype)]
        if text:
            features = features.assign(**{c: pd.to_numeric(features[c], errors="coerce") for c in text})
        # float64 here, as the preprocessor would make it anyway
        values = features.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)   # a view may be read-only
        # Zero-duration flows produce inf rates; training data had them removed, the imputer handles NaN
        values[np.isinf(values)] = np.nan
        features = pd.DataFrame(values, columns=self.required)
        metadata = df[[c for c in METADATA_COLUMNS if c in df.columns]].reset_index(drop=True)
        label = df[LABEL_COLUMN].reset_index(drop=True) if LABEL_COLUMN in df.columns else None
        return PreparedFlows(features, metadata, label, np.isnan(values).sum(axis=1), renamed)

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Metadata columns + decision, reason, predicted_class, class_name, scores, imputed_cells."""
        return self.predict_prepared(self.prepare(df))

    def predict_prepared(self, prepared: PreparedFlows) -> pd.DataFrame:
        """predict() for flows already through prepare(), when the caller also needs the features."""
        n = len(prepared.features)
        if n == 0:  # scikit-learn refuses zero rows
            result = pd.DataFrame(columns=["decision", "reason", "predicted_class",
                                           "confidence", "attack_score", "anomaly_score"])
        else:
            result = pd.concat([self.bundle.predict(prepared.features.iloc[i:i + self.batch_size])
                                for i in range(0, n, self.batch_size)], ignore_index=True)

        result.insert(result.columns.get_loc("predicted_class") + 1, "class_name",
                      result["predicted_class"].map(lambda c: self.class_names[str(int(c))]))
        result["imputed_cells"] = prepared.imputed_cells
        return pd.concat([prepared.metadata, result], axis=1)
