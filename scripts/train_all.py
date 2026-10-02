"""Train every model the backend uses (intent, off-topic gate, ranker).

    py -3 scripts/train_all.py

Model files are build artefacts and are not committed: the Docker images run
this at build time, and a fresh checkout runs it once before starting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = ["train_intent_classifier.py", "train_outlier.py", "train_ranker.py"]


def main() -> None:
    for script in STEPS:
        print(f"== {script}", flush=True)
        subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT / "backend", check=True)


if __name__ == "__main__":
    main()
