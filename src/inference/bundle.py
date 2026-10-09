"""
Model bundle: everything the server needs to turn raw flows into predictions, switched as a unit — feature selector + preprocessor + classifier, a manifest, and a self-test.
"""

import json
import hashlib
import platform
from dataclasses import dataclass
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MANIFEST = "manifest.json"
SELFTEST = "selftest.parquet"
ARTIFACTS = ("feature_selector.pkl", "preprocessor.pkl", "classifier.pkl")

EXPECTED_CLASS_COL = "__expected_class"
EXPECTED_PROBA_PREFIX = "__expected_proba_"

RECORDED_LIBRARIES = ("numpy", "pandas", "scikit-learn", "xgboost", "joblib")
# Pickled models only load reliably with the same major.minor of these
STRICT_LIBRARIES = ("scikit-learn", "xgboost")


class BundleError(Exception):
    pass


def library_versions() -> dict:
    versions = {"python": platform.python_version()}
    for lib in RECORDED_LIBRARIES:
        try:
            versions[lib] = version(lib)
        except PackageNotFoundError:
            versions[lib] = None
    return versions


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Bundle:
    path: Path
    manifest: dict
    selector: object
    preprocessor: object
    classifier: object

    @property
    def bundle_id(self) -> str:
        return self.manifest["bundle_id"]

    @property
    def classes(self) -> np.ndarray:
        return np.asarray(self.classifier.classes_)

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Raw flow features -> model input."""
        return self.preprocessor.transform(self.selector.transform(df))

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict_proba(self.transform(df))

    def selftest(self):
        df = pd.read_parquet(self.path / SELFTEST)
        expected_class = df.pop(EXPECTED_CLASS_COL).to_numpy()
        proba_cols = [c for c in df.columns if c.startswith(EXPECTED_PROBA_PREFIX)]
        expected_proba = df[proba_cols].to_numpy()

        proba = self.predict_proba(df.drop(columns=proba_cols))
        predicted = self.classes[proba.argmax(axis=1)]
        if not np.array_equal(predicted, expected_class) or not np.allclose(proba, expected_proba, atol=1e-6):
            n_wrong = int((predicted != expected_class).sum())
            raise BundleError(f"Bundle {self.bundle_id}: self-test failed "
                              f"({n_wrong}/{len(df)} predictions differ from the recorded ones)")


def _check_hashes(path: Path, manifest: dict):
    # Checked before unpickling anything: loading a pickle runs code
    for name, expected in manifest["files"].items():
        file = path / name
        if not file.exists():
            raise BundleError(f"{path.name}: missing file {name}")
        if sha256(file) != expected:
            raise BundleError(f"{path.name}: {name} does not match its SHA-256 in the manifest")


def _check_versions(path: Path, manifest: dict):
    installed = library_versions()
    for lib in STRICT_LIBRARIES:
        built, have = manifest["versions"].get(lib), installed.get(lib)
        if built and (have is None or built.split(".")[:2] != have.split(".")[:2]):
            raise BundleError(f"{path.name}: built with {lib} {built}, installed is {have}; "
                              f"rebuild the bundle or install {lib}=={built}")


def save_bundle(path: Path, manifest: dict, selector, preprocessor, classifier,
                selftest_df: pd.DataFrame) -> dict:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    for name, obj in zip(ARTIFACTS, (selector, preprocessor, classifier)):
        joblib.dump(obj, path / name)
    selftest_df.to_parquet(path / SELFTEST, index=False)

    manifest = {
        **manifest,
        "files": {name: sha256(path / name) for name in (*ARTIFACTS, SELFTEST)},
        "versions": library_versions(),
    }
    (path / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_bundle(path, verify: bool = True) -> Bundle:
    """Load a bundle; with verify, check hashes and library versions first, then run the self-test."""
    path = Path(path)
    manifest_file = path / MANIFEST
    if not manifest_file.exists():
        raise BundleError(f"{path}: no {MANIFEST}")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    if verify:
        _check_hashes(path, manifest)
        _check_versions(path, manifest)

    bundle = Bundle(path, manifest, *(joblib.load(path / name) for name in ARTIFACTS))
    if verify:
        bundle.selftest()
    return bundle
