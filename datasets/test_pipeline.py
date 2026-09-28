import unittest
from collections import Counter

from clean_data import (
    _deduplicate_labeled_records,
    _optional_coordinate,
    _parse_flood_date,
    clean_text,
    split_records,
)
from train_models import _region_from_record, evaluate_region_holdouts


class DataPipelineTests(unittest.TestCase):
    def test_clean_text_normalizes_spacing(self):
        self.assertEqual(clean_text("  heavy\n rain\treported "), "heavy rain reported")

    def test_conflicting_duplicate_labels_are_excluded(self):
        records = [
            {"text": "same report", "label": "disaster", "report_id": "one"},
            {"text": " same   report ", "label": "non_disaster", "report_id": "two"},
            {"text": "unique report", "label": "disaster", "report_id": "three"},
            {"text": "unique report", "label": "disaster", "report_id": "four"},
        ]
        result = _deduplicate_labeled_records(records)
        self.assertEqual([row["report_id"] for row in result], ["three"])

    def test_flood_date_and_coordinates_are_parsed_without_guessing(self):
        self.assertEqual(_parse_flood_date("02-07-1967 00:00"), "1967-07-02")
        self.assertEqual(_parse_flood_date("unknown"), "")
        self.assertEqual(_optional_coordinate("23.4", -90, 90), "23.4")
        self.assertEqual(_optional_coordinate("not-a-number", -90, 90), "")
        self.assertEqual(_optional_coordinate("91", -90, 90), "")

    def test_split_is_stratified_and_80_10_10(self):
        records = [
            {"text": f"example {index}", "label": "disaster" if index < 100 else "non_disaster"}
            for index in range(200)
        ]
        result = split_records(records)
        counts = Counter(row["split"] for row in result)
        self.assertEqual(counts, {"train": 160, "validation": 20, "test": 20})
        for split in ("train", "validation", "test"):
            labels = Counter(row["label"] for row in result if row["split"] == split)
            self.assertEqual(labels["disaster"], labels["non_disaster"])

    def test_region_is_read_from_mendeley_id_only(self):
        self.assertEqual(
            _region_from_record({"report_id": "mendeley_india_dataset_1"}),
            "india",
        )
        self.assertEqual(
            _region_from_record({"report_id": "mendeley_nepal_dataset_1"}),
            "nepal",
        )
        self.assertIsNone(_region_from_record({"report_id": "zenodo_ifi_1"}))

    def test_region_holdout_keeps_held_out_region_out_of_training(self):
        records = []
        for region in ("india", "nepal"):
            for label, phrase in (("disaster", "flood emergency"), ("non_disaster", "normal sunny day")):
                for index in range(4):
                    records.append(
                        {
                            "report_id": f"mendeley_{region}_record_{label}_{index}",
                            "text": f"{phrase} example {index} {region}",
                            "label": label,
                        }
                    )
        result = evaluate_region_holdouts(records)
        self.assertTrue(result["available"])
        self.assertEqual(set(result["region_results"]), {"india", "nepal"})
        for held_out, evaluation in result["region_results"].items():
            self.assertEqual(evaluation["test_region"], held_out)
            self.assertNotIn(held_out, evaluation["train_regions"])
            self.assertEqual(evaluation["test_rows"], 8)
            self.assertEqual(evaluation["train_rows"], 8)
            self.assertEqual(set(evaluation["classes"]), {"disaster", "non_disaster"})


if __name__ == "__main__":
    unittest.main()
