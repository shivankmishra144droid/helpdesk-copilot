"""Train IsolationForest outlier gate from active issue corpus.

Run from project root:
    cd backend
    py -3 ../scripts/train_outlier.py --caller-type both
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from kb_manager import KnowledgeRegistry, VALID_CALLER_TYPES, bind_registry  # noqa: E402
from outlier_gate import train_outlier_model  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Helpdesk Copilot outlier gate")
    parser.add_argument(
        "--caller-type",
        choices=[*VALID_CALLER_TYPES, "both"],
        default="both",
        help="Train for seller, buyer, or both (default: both)",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.05,
        help="IsolationForest contamination (default: 0.05)",
    )
    args = parser.parse_args()

    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    registry = KnowledgeRegistry(embed_model)
    bind_registry(registry)
    registry.reload_all()

    targets = (
        list(VALID_CALLER_TYPES)
        if args.caller_type == "both"
        else [args.caller_type]
    )

    for caller_type in targets:
        path = train_outlier_model(
            caller_type,
            embed_model=embed_model,
            contamination=args.contamination,
        )
        print(f"Outlier model saved: {path}")


if __name__ == "__main__":
    main()
