"""
Naming of the fitted preprocessing artifacts (feature selector + preprocessor).
"""

from pathlib import Path

DEFAULT_FS_PROFILE = "none"


def get_fs_profile(experiment: dict) -> str:
    return experiment.get("feature_selection") or DEFAULT_FS_PROFILE


def preprocessing_artifact_paths(config: dict, split_name: str, label_type: str,
                                 fs_profile: str = DEFAULT_FS_PROFILE, root=None):
    preproc_dir = Path(config["output"]["preprocessors_dir"])
    if root is not None:
        preproc_dir = Path(root) / preproc_dir

    stem = f"{split_name}_{label_type}_{fs_profile}"
    return (
        preproc_dir / f"{stem}_feature_selector.pkl",
        preproc_dir / f"{stem}_preprocessor.pkl",
    )
