"""
Which configuration the pipeline scripts read: configs/config.yaml, or the file named by AI_IDS_CONFIG.

The output paths inside the config are relative to the working directory, so another config run from
another directory leaves the project's dataset/, models/ and results/ alone
(scripts/pipeline_smoke.py does that in CI).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV = "AI_IDS_CONFIG"


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_ENV) or PROJECT_ROOT / "configs" / "config.yaml")
