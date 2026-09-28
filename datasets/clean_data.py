from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable


DATASETS_ROOT = Path(__file__).resolve().parent
SOCIAL_ROOT = DATASETS_ROOT / "raw" / "social" / "source_files" / "dataset"
FLOOD_ROOT = DATASETS_ROOT / "raw" / "flood"
PROCESSED_ROOT = DATASETS_ROOT / "processed"
MODEL_ROOT = DATASETS_ROOT / "models"
SEED = 42

COMMON_FIELDS = (
    "report_id",
    "text",
    "event_type",
    "location",
    "state",
    "latitude",
    "longitude",
    "date",
    "source",
    "label",
    "dataset_type",
)
SOCIAL_DETECTION_FILES = (
    ("TweetMasterData.csv", "nepal"),
    ("INDIANTWEETMASTER.csv", "india"),
)
SOCIAL_EVENT_FILES = (
    ("TWEETDATASET( CLASS 0,1 AND 2).csv", "nepal"),
    ("INDIANTWEETDATASET.csv", "india"),
)
EVENT_LABELS = {0: "", 1: "Flood", 2: "Earthquake"}


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_target(value: str, source_path: Path) -> int:
    try:
        target = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid Target value {value!r} in {source_path}") from error
    if target not in (0, 1, 2):
        raise ValueError(f"Unsupported Target value {target} in {source_path}")
    return target


def _read_labeled_tweets(
    files: Iterable[tuple[str, str]], task: str
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for filename, region in files:
        path = SOCIAL_ROOT / filename
        if not path.is_file():
            raise FileNotFoundError(
                f"Expected extracted Mendeley file {path}. "
                "Download the source archive and extract it to datasets/raw/social/source_files."
            )
        with path.open(encoding="utf-8-sig", newline="") as input_file:
            reader = csv.DictReader(input_file)
            if reader.fieldnames:
                reader.fieldnames = [field.strip() for field in reader.fieldnames]
            required = {"Tweet_id", "Tweet_text", "Target"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError(
                    f"{path} must contain columns {sorted(required)}; found {reader.fieldnames}."
                )
            for row_number, row in enumerate(reader, start=2):
                text = clean_text(row.get("Tweet_text"))
                if not text:
                    continue
                target = parse_target(row.get("Target", ""), path)
                event_type = EVENT_LABELS[target] if task == "event_type" else (
                    "Unclassified" if target == 1 else ""
                )
                label = (
                    ("non_disaster" if target == 0 else "disaster")
                    if task == "disaster"
                    else EVENT_LABELS[target] or "non_disaster"
                )
                tweet_id = clean_text(row.get("Tweet_id")) or str(row_number)
                records.append(
                    {
                        "report_id": f"mendeley_{region}_{filename.removesuffix('.csv')}_{tweet_id}",
                        "text": text,
                        "event_type": event_type,
                        "location": "",
                        "state": "",
                        "latitude": "",
                        "longitude": "",
                        "date": "",
                        "source": "Mendeley Data 10.17632/psv6b4zy9f.1",
                        "label": label,
                        "dataset_type": task,
                    }
                )
    return _deduplicate_labeled_records(records)


def _deduplicate_labeled_records(
    records: list[dict[str, str]],
) -> list[dict[str, str]]:
    labels_by_text: dict[str, set[str]] = {}
    for record in records:
        key = clean_text(record["text"]).casefold()
        labels_by_text.setdefault(key, set()).add(record["label"])
    conflicting_texts = {
        text for text, labels in labels_by_text.items() if len(labels) > 1
    }

    unique_records: dict[str, dict[str, str]] = {}
    for record in records:
        key = clean_text(record["text"]).casefold()
        if key in conflicting_texts:
            continue
        unique_records.setdefault(key, record)
    return list(unique_records.values())


def _parse_flood_date(value: str) -> str:
    normalized = clean_text(value)
    if not normalized:
        return ""
    for date_format in ("%d-%m-%Y %H:%M", "%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def _optional_coordinate(value: str, minimum: float, maximum: float) -> str:
    normalized = clean_text(value)
    if not normalized:
        return ""
    try:
        coordinate = float(normalized)
    except ValueError:
        return ""
    if not minimum <= coordinate <= maximum:
        return ""
    return str(coordinate)


def _read_flood_inventory() -> list[dict[str, str]]:
    path = FLOOD_ROOT / "India_Flood_Inventory_v3.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Expected the original Zenodo inventory at {path}.")
    records: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if reader.fieldnames:
            reader.fieldnames = [field.strip() for field in reader.fieldnames]
        required = {"UEI", "Start Date", "Main Cause", "Location", "Districts", "State"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"{path} must contain columns {sorted(required)}; found {reader.fieldnames}."
            )
        for row_number, row in enumerate(reader, start=2):
            main_cause = clean_text(row.get("Main Cause"))
            description = clean_text(row.get("Description of Casualties/injured"))
            damage = clean_text(row.get("Extent of damage"))
            text_parts = [
                part for part in (main_cause, description, damage) if part
            ]
            report_id = clean_text(row.get("UEI")) or f"zenodo_flood_row_{row_number}"
            records.append(
                {
                    "report_id": f"zenodo_ifi_{report_id}",
                    "text": " | ".join(text_parts) or "Historical flood inventory event",
                    "event_type": "Flood",
                    "location": clean_text(row.get("Location")) or clean_text(row.get("Districts")),
                    "state": clean_text(row.get("State")),
                    "latitude": _optional_coordinate(row.get("Latitude", ""), -90, 90),
                    "longitude": _optional_coordinate(row.get("Longitude", ""), -180, 180),
                    "date": _parse_flood_date(row.get("Start Date", "")),
                    "source": "IIT Delhi IFI-Impacts v4, Zenodo 10.5281/zenodo.16994648",
                    "label": "historical_flood_event",
                    "dataset_type": "historical_flood_evidence",
                }
            )
    return records


def _write_csv(path: Path, fields: tuple[str, ...], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_records(
    records: list[dict[str, str]], *, seed: int = SEED
) -> list[dict[str, str]]:
    if not records:
        raise ValueError("Cannot split an empty dataset.")
    try:
        from sklearn.model_selection import train_test_split
    except ImportError as error:
        raise RuntimeError(
            "Install the project requirements before creating the ML splits."
        ) from error

    labels = [record["label"] for record in records]
    class_counts: dict[str, int] = {}
    for label in labels:
        class_counts[label] = class_counts.get(label, 0) + 1
    if min(class_counts.values()) < 3:
        raise ValueError(
            "Each class needs at least three records for stratified 80/10/10 splitting."
        )

    indices = list(range(len(records)))
    train_indices, holdout_indices = train_test_split(
        indices,
        test_size=0.2,
        random_state=seed,
        stratify=labels,
    )
    holdout_labels = [labels[index] for index in holdout_indices]
    validation_indices, test_indices = train_test_split(
        holdout_indices,
        test_size=0.5,
        random_state=seed,
        stratify=holdout_labels,
    )
    split_by_index = {
        **{index: "train" for index in train_indices},
        **{index: "validation" for index in validation_indices},
        **{index: "test" for index in test_indices},
    }
    return [
        {**record, "split": split_by_index[index]}
        for index, record in enumerate(records)
    ]


def run_pipeline() -> dict[str, int]:
    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)

    disaster_records = _read_labeled_tweets(SOCIAL_DETECTION_FILES, "disaster")
    event_records = _read_labeled_tweets(SOCIAL_EVENT_FILES, "event_type")
    flood_records = _read_flood_inventory()
    common_records = [*disaster_records, *event_records, *flood_records]

    _write_csv(PROCESSED_ROOT / "social_disaster.csv", COMMON_FIELDS, disaster_records)
    _write_csv(PROCESSED_ROOT / "social_event_type.csv", COMMON_FIELDS, event_records)
    _write_csv(
        PROCESSED_ROOT / "weather_events.csv",
        COMMON_FIELDS,
        common_records,
    )
    split_fields = (*COMMON_FIELDS, "split")
    disaster_splits = split_records(disaster_records)
    event_splits = split_records(event_records)
    _write_csv(
        PROCESSED_ROOT / "social_disaster_splits.csv",
        split_fields,
        disaster_splits,
    )
    _write_csv(
        PROCESSED_ROOT / "social_event_type_splits.csv",
        split_fields,
        event_splits,
    )

    return {
        "social_disaster": len(disaster_records),
        "social_event_type": len(event_records),
        "historical_flood_evidence": len(flood_records),
        "common_schema": len(common_records),
    }


if __name__ == "__main__":
    counts = run_pipeline()
    for name, count in counts.items():
        print(f"{name}: {count:,} rows")
