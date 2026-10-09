"""
Per-flow explanations: which features drove a flow's decision.
Explainers are built once per bundle (~1 s) and reused; one flow takes a few ms.
"""

import numpy as np
import pandas as pd
import shap

from src.models.label_encoded import LabelEncodedClassifier

TOP_N = 15


class FlowExplainer:

    def __init__(self, bundle, top_n=TOP_N):
        self.bundle = bundle
        self.top_n = top_n
        self.features = list(bundle.manifest["required_features"])
        self.class_names = bundle.manifest["class_names"]
        self.benign_profile = bundle.manifest.get("benign_profile", {})

        classifier = bundle.classifier
        if isinstance(classifier, LabelEncodedClassifier):
            classifier = classifier.estimator_  # explain the fitted XGBoost booster
        self._model_type = type(classifier).__name__
        self._classifier_explainer = shap.TreeExplainer(classifier)
        self._anomaly_explainer = shap.TreeExplainer(bundle.anomaly_detector)

    def explain(self, flow: pd.DataFrame, result=None) -> dict:
        """Explain one flow (a one-row DataFrame of raw features). Returns JSON-ready dict.

        Pass the flow's stored prediction as `result` (a row of Bundle.predict output) to skip
        predicting it again; it must come from this same bundle.
        """
        if len(flow) != 1:
            raise ValueError(f"explain() takes one flow, got {len(flow)} rows")
        X = self.bundle.transform(flow)
        # Transformed columns follow required_features (all numeric, ColumnTransformer keeps order)
        assert X.shape[1] == len(self.features), "model input does not line up with required_features"
        if result is None:
            result = self.bundle.predict(flow).iloc[0]
        raw = flow[self.features].iloc[0]
        predicted = int(result["predicted_class"])

        if result["reason"] == "anomalous":
            explanations = [self._anomaly(X, raw)]
        elif result["reason"] == "low_confidence":
            proba = self.bundle.classifier.predict_proba(X)[0]
            top_two = np.argsort(proba)[::-1][:2]
            explanations = [self._toward_class(X, raw, int(self.bundle.classes[i])) for i in top_two]
        else:
            explanations = [self._toward_class(X, raw, predicted)]

        return {
            "bundle_id": self.bundle.bundle_id,
            "decision": result["decision"],
            "reason": result["reason"],
            "predicted_class": predicted,
            "class_name": self.class_names[str(predicted)],
            "confidence": float(result["confidence"]),
            "attack_score": float(result["attack_score"]),
            "anomaly_score": float(result["anomaly_score"]),
            "explanations": explanations,
        }

    def _toward_class(self, X, raw, cls):
        values = self._classifier_explainer.shap_values(X)
        k = list(self.bundle.classes).index(cls)
        if isinstance(values, list):  # older shap: one array per class
            contributions = values[k][0]
        elif values.ndim == 3:        # (rows, features, classes)
            contributions = values[0, :, k]
        else:                         # single-output model
            contributions = values[0]
        base = np.atleast_1d(self._classifier_explainer.expected_value)
        return {
            "target": "class",
            "class": cls,
            "class_name": self.class_names[str(cls)],
            "output_space": "log_odds" if self._model_type == "XGBClassifier" else "probability",
            "base_value": float(base[k] if len(base) > 1 else base[0]),
            "contributions": self._top(contributions, raw),
        }

    def _anomaly(self, X, raw):
        contributions = -self._anomaly_explainer.shap_values(X)[0]
        top = self._top(contributions, raw)
        for item in top:
            profile = self.benign_profile.get(item["feature"])
            if profile and profile["std"] > 0 and item["value"] is not None:
                item["benign_median"] = profile["median"]
                item["deviation_sd"] = (item["value"] - profile["median"]) / profile["std"]
        return {
            "target": "anomaly",
            "output_space": "anomaly_score",
            "base_value": float(-np.atleast_1d(self._anomaly_explainer.expected_value)[0]),
            "contributions": top,
        }

    def _top(self, contributions, raw):
        order = np.argsort(-np.abs(contributions))[: self.top_n]
        top = []
        for i in order:
            value = float(raw.iloc[i])
            top.append({"feature": self.features[i],
                        "value": value if np.isfinite(value) else None,  # missing values were imputed
                        "contribution": float(contributions[i])})
        return top
