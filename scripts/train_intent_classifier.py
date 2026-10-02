"""Train supervised intent classifier from KB branch topic categories."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from category_utils import load_topic_categories, normalize_caller_type  # noqa: E402
from intent_classifier import (  # noqa: E402
    EMBED_MODEL_NAME,
    build_category_prototypes,
    save_supervised_bundle,
    train_supervised_intent_classifier,
)
from kb_manager import KnowledgeRegistry, VALID_CALLER_TYPES, bind_registry  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _branch_training_examples(branch: dict) -> list[str]:
    examples: list[str] = []
    name = branch.get("branch_name", "").strip()
    if name:
        examples.append(name)
    for keyword in branch.get("trigger_keywords", []):
        keyword = str(keyword).strip()
        if keyword:
            examples.append(keyword)
            if name:
                examples.append(f"{keyword} {name}")
    return examples


def build_training_corpus(caller_type: str) -> tuple[list[str], list[str]]:
    from kb_manager import get_kb

    store = get_kb(caller_type)
    texts: list[str] = []
    labels: list[str] = []
    valid_ids = {item["id"] for item in load_topic_categories(caller_type)}

    for branch in store.branches:
        category_id = branch.get("topic_category")
        if not category_id or category_id not in valid_ids:
            continue
        for example in _branch_training_examples(branch):
            texts.append(example)
            labels.append(category_id)

    return texts, labels


def evaluate_model(
    model,
    label_encoder: LabelEncoder,
    embed_model: SentenceTransformer,
    texts: list[str],
    labels: list[str],
) -> dict:
    vectors = embed_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float32)
    encoded = label_encoder.transform(labels)
    predictions = model.predict(vectors)

    report = classification_report(
        encoded,
        predictions,
        target_names=list(label_encoder.classes_),
        output_dict=True,
        zero_division=0,
    )
    return {
        "accuracy": round(float(accuracy_score(encoded, predictions)), 4),
        "macro_f1": round(float(f1_score(encoded, predictions, average="macro")), 4),
        "per_category": {
            label_encoder.classes_[index]: report.get(label_encoder.classes_[index], {})
            for index in range(len(label_encoder.classes_))
        },
        "confusion_matrix": confusion_matrix(encoded, predictions).tolist(),
        "labels": list(label_encoder.classes_),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Helpdesk Copilot intent classifier")
    parser.add_argument(
        "--caller-type",
        choices=[*VALID_CALLER_TYPES, "both"],
        default="both",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    registry = KnowledgeRegistry(embed_model)
    bind_registry(registry)
    registry.reload_all()

    targets = (
        list(VALID_CALLER_TYPES)
        if args.caller_type == "both"
        else [args.caller_type]
    )

    bundle: dict = {
        "version": 1,
        "embed_model_name": EMBED_MODEL_NAME,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "models": {},
        "label_encoders": {},
        "validation_metrics": {},
        "training_counts": {},
    }

    for caller_type in targets:
        texts, labels = build_training_corpus(caller_type)
        label_counts = Counter(labels)
        logger.info(
            "%s training examples: %s across %s categories",
            caller_type,
            len(texts),
            len(label_counts),
        )
        if len(texts) < 10 or len(label_counts) < 2:
            logger.warning(
                "Skipping %s — need at least 10 examples and 2 categories",
                caller_type,
            )
            continue

        if len(set(labels)) < 2 or len(texts) < 4:
            continue

        try:
            train_texts, val_texts, train_labels, val_labels = train_test_split(
                texts,
                labels,
                test_size=args.test_size,
                random_state=args.random_state,
                stratify=labels,
            )
        except ValueError:
            train_texts, val_texts, train_labels, val_labels = train_test_split(
                texts,
                labels,
                test_size=args.test_size,
                random_state=args.random_state,
            )

        model, label_encoder = train_supervised_intent_classifier(
            caller_type,
            embed_model,
            texts=train_texts,
            labels=train_labels,
        )
        metrics = evaluate_model(
            model,
            label_encoder,
            embed_model,
            val_texts,
            val_labels,
        )

        bundle["models"][caller_type] = model
        bundle["label_encoders"][caller_type] = label_encoder
        bundle["validation_metrics"][caller_type] = metrics
        bundle["training_counts"][caller_type] = {
            "examples": len(texts),
            "categories": len(label_counts),
            "label_distribution": dict(label_counts),
        }

        print(f"\n=== {caller_type} validation ===")
        print(f"accuracy: {metrics['accuracy']}")
        print(f"macro_f1: {metrics['macro_f1']}")
        print("confusion_matrix labels:", metrics["labels"])
        print(json.dumps(metrics["confusion_matrix"], indent=2))

        prototypes = build_category_prototypes(caller_type, embed_model)
        bundle.setdefault("prototype_counts", {})[caller_type] = len(prototypes)

    if not bundle["models"]:
        print("No caller types trained — not enough labeled KB data.")
        return

    path = save_supervised_bundle(bundle)
    print(f"\nIntent classifier saved: {path}")


if __name__ == "__main__":
    main()
