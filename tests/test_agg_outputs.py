#!/usr/bin/env python3

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agg_outputs", ROOT / "scripts" / "agg_outputs.py"
)
AGG_OUTPUTS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AGG_OUTPUTS)


class AggregateOutputsTests(unittest.TestCase):
    def write_stats(self, directory: Path, payload: dict) -> None:
        path = directory / "run_a_01_h_24_l_08_s_32768_n_01_r_00_stats.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

    def aggregate_and_export(self, payload: dict):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        outputs = root / "outputs"
        outputs.mkdir()
        self.write_stats(outputs, payload)
        aggregated = AGG_OUTPUTS.aggregate_outputs(outputs, root)
        csv_path = root / "pruning.csv"
        AGG_OUTPUTS.export_pruning_csv(aggregated, csv_path, quiet=True)
        with csv_path.open(newline="", encoding="utf-8") as stream:
            rows = {row[0]: row[1:] for row in csv.reader(stream)}
        return aggregated["runs"][0]["prune_counts_by_type_hour"], rows

    def test_legacy_levels_are_exported_as_tank_levels(self) -> None:
        raw, rows = self.aggregate_and_export(
            {"NONE": [6], "LEVELS": [4]}
        )

        self.assertEqual(raw["LEVELS"], [4])
        self.assertEqual(rows["Tank levels"], ["40.0"])
        self.assertEqual(rows["Total pruned"], ["40.0"])
        self.assertEqual(rows["Feasible"], ["60.0"])
        self.assertEqual(rows["Nodes (total)"], ["10"])

    def test_current_saturation_is_exported_as_tank_levels(self) -> None:
        raw, rows = self.aggregate_and_export(
            {"NONE": [6], "TANK_SATURATION": [4]}
        )

        self.assertEqual(raw["TANK_SATURATION"], [4])
        self.assertEqual(rows["Tank levels"], ["40.0"])
        self.assertEqual(rows["Total pruned"], ["40.0"])
        self.assertEqual(rows["Feasible"], ["60.0"])
        self.assertEqual(rows["Nodes (total)"], ["10"])

    def test_distinct_tank_reasons_are_preserved_and_grouped(self) -> None:
        raw, rows = self.aggregate_and_export(
            {
                "NONE": [5, 0],
                "LEVELS": [2, 0],
                "TANK_SATURATION": [0, 3],
            }
        )

        self.assertEqual(raw["LEVELS"], [2, 0])
        self.assertEqual(raw["TANK_SATURATION"], [0, 3])
        self.assertEqual(rows["Tank levels"], ["50.0"])
        self.assertEqual(rows["Total pruned"], ["50.0"])
        self.assertEqual(rows["Feasible"], ["50.0"])
        self.assertEqual(rows["Nodes (total)"], ["10"])

    def test_total_pruned_uses_raw_counts_including_minor_reasons(self) -> None:
        _, rows = self.aggregate_and_export(
            {
                "NONE": [1],
                "ACTUATIONS": [1],
                "COST": [1],
                "LEVELS": [1],
                "PRESSURES": [1],
                "STABILITY": [1],
            }
        )

        self.assertEqual(rows["Total pruned"], ["83.3"])
        self.assertEqual(rows["Feasible"], ["16.7"])
        self.assertEqual(rows["Nodes (total)"], ["6"])


if __name__ == "__main__":
    unittest.main()
