"""Train XGBoost search re-ranker from synthetic query data.

Run from project root:
    cd backend
    py -3 ../scripts/train_ranker.py --samples-per-branch 50
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from kb_manager import KnowledgeRegistry, bind_registry  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402
from xgboost_ranker import train_and_save_all  # noqa: E402

logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Helpdesk Copilot XGBoost ranker")
    parser.add_argument(
        "--samples-per-branch",
        type=int,
        default=50,
        help="Synthetic query variations per KB branch (default: 50)",
    )
    args = parser.parse_args()

    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    registry = KnowledgeRegistry(embed_model)
    bind_registry(registry)
    registry.reload_all()

    path = train_and_save_all(samples_per_branch=args.samples_per_branch)
    print(f"Ranker saved to {path}")


if __name__ == "__main__":
    main()
