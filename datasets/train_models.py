from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASETS_ROOT = Path(__file__).resolve().parent
PROCESSED_ROOT = DATASETS_ROOT / "processed"
MODEL_ROOT = DATASETS_ROOT / "models"
SEED = 42
SOURCE = "Mendeley Data 10.17632/psv6b4zy9f.1"
REGION_PATTERN = re.compile(r"^mendeley_(india|nepal)_", re.IGNORECASE)


def _region_from_record(record: dict[str, str]) -> str | None:
    match = REGION_PATTERN.match(record.get("report_id", ""))
    return match.group(1).lower() if match else None


def _build_model():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    strip_accents="unicode",
                    ngram_range=(1, 2),
                    min_df=2,
                    max_features=100_000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=SEED,
                ),
            ),
        ]
    )


def evaluate_region_holdouts(records: list[dict[str, str]]) -> dict[str, Any]:
    try:
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
        )
    except ImportError as error:
        raise RuntimeError(
            "Install the project requirements before evaluating the models."
        ) from error

    regional_records: dict[str, list[dict[str, str]]] = {}
    for record in records:
        region = _region_from_record(record)
        if region:
            regional_records.setdefault(region, []).append(record)
    if len(regional_records) < 2:
        return {
            "available": False,
            "reason": "At least two source regions are required for regional holdout evaluation.",
        }

    results: dict[str, Any] = {}
    for held_out_region, test_rows in sorted(regional_records.items()):
        train_rows = [
            record
            for region, rows in regional_records.items()
            if region != held_out_region
            for record in rows
        ]
        train_classes = {row["label"] for row in train_rows}
        test_classes = {row["label"] for row in test_rows}
        missing_classes = sorted(test_classes - train_classes)
        if missing_classes:
            raise ValueError(
                f"Regional holdout for {held_out_region} has test labels absent "
                f"from training: {missing_classes}."
            )

        model = _build_model()
        train_texts = [row["text"] for row in train_rows]
        train_labels = [row["label"] for row in train_rows]
        test_texts = [row["text"] for row in test_rows]
        test_labels = [row["label"] for row in test_rows]
        model.fit(train_texts, train_labels)
        predictions = model.predict(test_texts)
        classes = sorted(test_classes)
        results[held_out_region] = {
            "train_regions": sorted(regional_records.keys() - {held_out_region}),
            "test_region": held_out_region,
            "train_rows": len(train_rows),
            "test_rows": len(test_rows),
            "accuracy": float(accuracy_score(test_labels, predictions)),
            "macro_f1": float(
                f1_score(test_labels, predictions, labels=classes, average="macro", zero_division=0)
            ),
            "classes": classes,
            "classification_report": classification_report(
                test_labels,
                predictions,
                labels=classes,
                output_dict=True,
                zero_division=0,
            ),
            "confusion_matrix": confusion_matrix(
                test_labels, predictions, labels=classes
            ).tolist(),
        }
    return {
        "available": True,
        "method": "Leave-one-source-region-out; all tweets from each held-out region are excluded from training.",
        "region_results": results,
    }


def _read_split(path: Path, split: str) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run `python datasets/clean_data.py` first."
        )
    with path.open(encoding="utf-8", newline="") as input_file:
        records = [row for row in csv.DictReader(input_file) if row["split"] == split]
    if not records:
        raise ValueError(f"No {split} records found in {path}.")
    return records


def _train_task(
    *,
    name: str,
    filename: str,
    output_name: str,
    description: str,
) -> dict[str, Any]:
    try:
        import joblib
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
        )
    except ImportError as error:
        raise RuntimeError(
            "Install the project requirements before training the models."
        ) from error

    train_rows = _read_split(PROCESSED_ROOT / filename, "train")
    validation_rows = _read_split(PROCESSED_ROOT / filename, "validation")
    test_rows = _read_split(PROCESSED_ROOT / filename, "test")
    train_labels = [row["label"] for row in train_rows]
    class_counts = Counter(train_labels)
    if len(class_counts) < 2:
        raise ValueError(f"{name} needs at least two label classes in its training set.")

    model = _build_model()
    model.fit([row["text"] for row in train_rows], train_labels)
    validation_predictions = model.predict([row["text"] for row in validation_rows])
    test_texts = [row["text"] for row in test_rows]
    test_labels = [row["label"] for row in test_rows]
    test_predictions = model.predict(test_texts)
    classes = [str(value) for value in model.named_steps["classifier"].classes_]

    metrics = {
        "accuracy": float(accuracy_score(test_labels, test_predictions)),
        "classification_report": classification_report(
            test_labels,
            test_predictions,
            labels=classes,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(
            test_labels, test_predictions, labels=classes
        ).tolist(),
        "validation_accuracy": float(
            accuracy_score(
                [row["label"] for row in validation_rows], validation_predictions
            )
        ),
        "classes": classes,
        "train_class_counts": dict(class_counts),
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "test_rows": len(test_rows),
    }

    regional_evaluation = evaluate_region_holdouts(
        [*train_rows, *validation_rows, *test_rows]
    )
    metadata = {
        "task": name,
        "description": description,
        "source": SOURCE,
        "license": "CC BY 4.0",
        "random_seed": SEED,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "temporal_evaluation": {
            "available": False,
            "reason": "The Mendeley tweet files used in this task have no usable event-date field.",
        },
        "regional_holdout_evaluation": regional_evaluation,
        **metrics,
    }
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"pipeline": model, "metadata": metadata},
        MODEL_ROOT / output_name,
    )
    (MODEL_ROOT / f"{name}_evaluation.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (MODEL_ROOT / f"{name}_regional_evaluation.json").write_text(
        json.dumps(regional_evaluation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return metadata


def train_models() -> dict[str, dict[str, Any]]:
    return {
        "disaster_detection": _train_task(
            name="disaster_detection",
            filename="social_disaster_splits.csv",
            output_name="disaster_detection.joblib",
            description="Social-media disaster vs non-disaster text classification; not event verification.",
        ),
        "event_type": _train_task(
            name="event_type",
            filename="social_event_type_splits.csv",
            output_name="event_type.joblib",
            description="Social-media label classification into non-disaster, flood, or earthquake.",
        ),
    }


if __name__ == "__main__":
    results = train_models()
    for task, result in results.items():
        print(
            f"{task}: test accuracy={result['accuracy']:.3f}; "
            f"validation accuracy={result['validation_accuracy']:.3f}; "
            f"test rows={result['test_rows']}"
        )
        regional = result["regional_holdout_evaluation"]
        for region, metrics in regional.get("region_results", {}).items():
            print(
                f"  held-out {region}: accuracy={metrics['accuracy']:.3f}; "
                f"macro F1={metrics['macro_f1']:.3f}; "
                f"test rows={metrics['test_rows']}"
            )
        temporal = result["temporal_evaluation"]
        if not temporal["available"]:
            print(f"  temporal evaluation unavailable: {temporal['reason']}")
