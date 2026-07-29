#!/usr/bin/env python3

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_tuning", ROOT / "scripts" / "run_tuning.py"
)
run_tuning = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_tuning)


class RunTuningTests(unittest.TestCase):
    def base_config(self):
        return {
            "mpi_launcher": "/usr/bin/mpiexec",
            "mpi_launcher_args": [],
            "binary": "/tmp/solver",
            "input": "/tmp/network.inp",
            "hours": 3,
            "max_actuations": 1,
            "hydraulic_accuracy": None,
            "hydraulic_max_trials": None,
        }

    def test_build_command_includes_input_and_search_parameters(self):
        command = run_tuning.build_command(
            self.base_config(),
            {"np": 2, "level": 1, "sync_interval": 32},
        )
        self.assertEqual(
            command,
            [
                "/usr/bin/mpiexec",
                "-n",
                "2",
                "/tmp/solver",
                "-i",
                "/tmp/network.inp",
                "-h",
                "3",
                "-a",
                "1",
                "-l",
                "1",
                "-s",
                "32",
            ],
        )

    def test_build_command_includes_hydraulic_overrides(self):
        config = self.base_config()
        config["hydraulic_accuracy"] = 1.0e-4
        config["hydraulic_max_trials"] = 80
        command = run_tuning.build_command(
            config, {"np": 1, "level": 1, "sync_interval": 64}
        )
        self.assertEqual(command[-4:], ["--hydraulic-accuracy", "0.0001",
                                        "--hydraulic-max-trials", "80"])

    def write_rank_artifacts(self, output_dir, rank, status="CONCLUSIVE"):
        stem = f"run_n_02_r_{rank:02d}"
        with (output_dir / f"{stem}_stats.json").open("w") as stream:
            json.dump({"search": {"status": status}}, stream)
        with (output_dir / f"{stem}_best.json").open("w") as stream:
            json.dump({"search_status": status, "best_cost": 100.0 + rank}, stream)

    def test_validate_artifacts_requires_every_rank_and_returns_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            output_dir = run_dir / "outputs"
            output_dir.mkdir()
            self.write_rank_artifacts(output_dir, 0)
            self.write_rank_artifacts(output_dir, 1)
            result = run_tuning.validate_artifacts(run_dir, expected_ranks=2)
        self.assertEqual(result["best_cost"], 100.0)
        self.assertEqual(len(result["stats_files"]), 2)
        self.assertEqual(len(result["best_files"]), 2)

    def test_validate_artifacts_rejects_inconclusive_rank(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            output_dir = run_dir / "outputs"
            output_dir.mkdir()
            self.write_rank_artifacts(output_dir, 0)
            self.write_rank_artifacts(output_dir, 1, "INCONCLUSIVE")
            with self.assertRaisesRegex(
                run_tuning.TrialRejected, "inconclusive search"
            ):
                run_tuning.validate_artifacts(run_dir, expected_ranks=2)

    def test_parameter_combinations_cover_the_grid(self):
        combinations = list(
            run_tuning.parameter_combinations(
                {"np": [1, 2], "level": [1], "sync_interval": [32, 64]}
            )
        )
        self.assertEqual(len(combinations), 4)
        self.assertEqual(
            {tuple(sorted(item.items())) for item in combinations},
            {
                (("level", 1), ("np", 1), ("sync_interval", 32)),
                (("level", 1), ("np", 1), ("sync_interval", 64)),
                (("level", 1), ("np", 2), ("sync_interval", 32)),
                (("level", 1), ("np", 2), ("sync_interval", 64)),
            },
        )

    def test_normalize_configuration_filters_np_with_max_np(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            binary = temp_dir / "fake_binary"
            binary.touch()
            binary.chmod(0o755)
            input_file = temp_dir / "input.inp"
            input_file.touch()
            output_dir = temp_dir / "out"

            raw_config = {
                "schema_version": 1,
                "study_name": "test_study",
                "binary": str(binary),
                "input": str(input_file),
                "output_dir": str(output_dir),
                "hours": 3,
                "max_actuations": 1,
                "search_space": {
                    "np": [1, 2, 4, 8],
                    "level": [1],
                    "sync_interval": [32],
                },
                "timeout_seconds": 100,
                "repetitions": 1,
                "sampler_seed": 42,
            }
            normalized = run_tuning.normalize_configuration(
                raw_config,
                config_path=temp_dir / "config.json",
                max_np_override=2,
            )
            self.assertEqual(normalized["search_space"]["np"], [1, 2])

    def test_normalize_configuration_accepts_racing_protocol(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            binary = temp_dir / "fake_binary"
            binary.touch()
            binary.chmod(0o755)
            input_file = temp_dir / "input.inp"
            input_file.touch()

            raw_config = {
                "schema_version": 1,
                "study_name": "racing_study",
                "binary": str(binary),
                "input": str(input_file),
                "output_dir": str(temp_dir / "out"),
                "hours": 24,
                "max_actuations": 2,
                "search_space": {
                    "np": [8, 64],
                    "level": [8, 9],
                    "sync_interval": [1024, 32768],
                },
                "timeout_seconds": 900,
                "repetitions": 3,
                "sampler_seed": 42,
                "racing": {
                    "relative_cutoff_factor": 1.25,
                    "initial_incumbent": {
                        "np": 64,
                        "level": 8,
                        "sync_interval": 32768,
                    },
                    "validation_repetitions": 3,
                },
            }

            normalized = run_tuning.normalize_configuration(
                raw_config,
                config_path=temp_dir / "config.json",
            )

        self.assertEqual(normalized["timeout_seconds"], 900.0)
        self.assertEqual(
            normalized["racing"],
            {
                "relative_cutoff_factor": 1.25,
                "initial_incumbent": {
                    "np": 64,
                    "level": 8,
                    "sync_interval": 32768,
                },
                "validation_repetitions": 3,
            },
        )

    def test_normalize_configuration_rejects_even_racing_repetition_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp_dir = Path(temporary)
            binary = temp_dir / "fake_binary"
            binary.touch()
            binary.chmod(0o755)
            input_file = temp_dir / "input.inp"
            input_file.touch()
            raw_config = {
                "schema_version": 1,
                "study_name": "racing_study",
                "binary": str(binary),
                "input": str(input_file),
                "output_dir": str(temp_dir / "out"),
                "hours": 24,
                "max_actuations": 2,
                "search_space": {
                    "np": [64],
                    "level": [8],
                    "sync_interval": [32768],
                },
                "timeout_seconds": 900,
                "repetitions": 2,
                "sampler_seed": 42,
                "racing": {
                    "relative_cutoff_factor": 1.25,
                    "initial_incumbent": {
                        "np": 64,
                        "level": 8,
                        "sync_interval": 32768,
                    },
                    "validation_repetitions": 3,
                },
            }

            with self.assertRaisesRegex(
                run_tuning.ConfigurationError, "odd repetitions"
            ):
                run_tuning.normalize_configuration(
                    raw_config,
                    config_path=temp_dir / "config.json",
                )

    def test_initial_incumbent_is_enqueued_once(self):
        study = mock.Mock()
        config = {
            "racing": {
                "initial_incumbent": {
                    "np": 64,
                    "level": 8,
                    "sync_interval": 32768,
                }
            }
        }

        run_tuning.enqueue_initial_incumbent(study, config)

        study.enqueue_trial.assert_called_once_with(
            {"np": 64, "level": 8, "sync_interval": 32768},
            skip_if_exists=True,
        )

    def racing_config(self):
        return {
            **self.base_config(),
            "search_space": {
                "np": [64],
                "level": [8],
                "sync_interval": [32768],
            },
            "timeout_seconds": 900.0,
            "repetitions": 3,
            "environment": {},
            "racing": {
                "relative_cutoff_factor": 1.25,
                "initial_incumbent": {
                    "np": 64,
                    "level": 8,
                    "sync_interval": 32768,
                },
                "validation_repetitions": 3,
            },
        }

    def racing_trial(self):
        incumbent = SimpleNamespace(
            number=0,
            state=SimpleNamespace(name="COMPLETE"),
            value=10.0,
            params={"np": 32, "level": 8, "sync_interval": 32768},
            user_attrs={"eligible_incumbent": True},
        )
        study = SimpleNamespace(trials=[incumbent])

        class FakeTrial:
            number = 1

            def __init__(self):
                self.study = study
                self.user_attrs = {}

            def suggest_categorical(self, name, _choices):
                return {
                    "np": 64,
                    "level": 8,
                    "sync_interval": 32768,
                }[name]

            def set_user_attr(self, name, value):
                self.user_attrs[name] = value

        return FakeTrial()

    def fake_optuna(self):
        class TrialPruned(Exception):
            pass

        return SimpleNamespace(TrialPruned=TrialPruned)

    @mock.patch.object(run_tuning, "validate_artifacts")
    @mock.patch.object(run_tuning, "run_process")
    def test_racing_prunes_only_after_two_relative_cutoffs(
        self, run_process_mock, validate_artifacts_mock
    ):
        run_process_mock.side_effect = [
            run_tuning.ProcessTimeout(12.5, 12.5),
            run_tuning.ProcessTimeout(12.5, 12.5),
        ]
        optuna = self.fake_optuna()
        with tempfile.TemporaryDirectory() as temporary:
            objective = run_tuning.create_objective(
                self.racing_config(), Path(temporary), optuna
            )
            trial = self.racing_trial()
            with self.assertRaisesRegex(optuna.TrialPruned, "median"):
                objective(trial)

        self.assertEqual(run_process_mock.call_count, 2)
        validate_artifacts_mock.assert_not_called()
        self.assertEqual(trial.user_attrs["racing_cutoff_count"], 2)
        self.assertEqual(trial.user_attrs["incumbent_seconds_at_start"], 10.0)
        self.assertEqual(trial.user_attrs["effective_timeout_seconds"], 12.5)

    @mock.patch.object(run_tuning, "validate_artifacts")
    @mock.patch.object(run_tuning, "run_process")
    def test_single_relative_cutoff_triggers_uncensored_validation(
        self, run_process_mock, validate_artifacts_mock
    ):
        run_process_mock.side_effect = [
            run_tuning.ProcessTimeout(12.5, 12.5),
            (0, 8.0),
            (0, 9.0),
            (0, 7.0),
            (0, 8.0),
            (0, 9.0),
        ]
        validate_artifacts_mock.return_value = {
            "best_cost": 100.0,
            "stats_files": ["outputs/stats.json"],
            "best_files": ["outputs/best.json"],
        }
        optuna = self.fake_optuna()
        with tempfile.TemporaryDirectory() as temporary:
            objective = run_tuning.create_objective(
                self.racing_config(), Path(temporary), optuna
            )
            trial = self.racing_trial()
            result = objective(trial)

        self.assertEqual(result, 8.0)
        self.assertEqual(run_process_mock.call_count, 6)
        self.assertEqual(trial.user_attrs["racing_cutoff_count"], 1)
        self.assertEqual(trial.user_attrs["racing_wall_times"], [12.5, 8.0, 9.0])
        self.assertEqual(trial.user_attrs["repetition_wall_times"], [7.0, 8.0, 9.0])
        self.assertTrue(trial.user_attrs["validation_performed"])
        self.assertTrue(trial.user_attrs["eligible_incumbent"])

    @mock.patch.object(run_tuning, "validate_artifacts")
    @mock.patch.object(run_tuning, "run_process")
    def test_real_optuna_grid_covers_unique_combinations_after_enqueue(
        self, run_process_mock, validate_artifacts_mock
    ):
        import optuna

        run_process_mock.return_value = (0, 1.0)
        validate_artifacts_mock.return_value = {
            "best_cost": 100.0,
            "stats_files": ["outputs/stats.json"],
            "best_files": ["outputs/best.json"],
        }
        config = self.racing_config()
        config["search_space"] = {
            "np": [1, 2],
            "level": [1],
            "sync_interval": [32, 64],
        }
        config["racing"]["initial_incumbent"] = {
            "np": 2,
            "level": 1,
            "sync_interval": 64,
        }
        all_combinations = {
            tuple(sorted(combination.items()))
            for combination in run_tuning.parameter_combinations(
                config["search_space"]
            )
        }
        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.GridSampler(
                config["search_space"], seed=20260724
            ),
        )
        run_tuning.enqueue_initial_incumbent(study, config)

        with tempfile.TemporaryDirectory() as temporary:
            objective = run_tuning.create_objective(
                config, Path(temporary), optuna
            )
            run_tuning.optimize_unique_parameter_sets(
                study,
                objective,
                all_combinations,
                requested=1,
                callback=lambda _study, _trial: None,
            )
            initial_key = tuple(
                sorted(config["racing"]["initial_incumbent"].items())
            )
            self.assertEqual(
                run_tuning.completed_parameter_sets(study),
                {initial_key},
            )
            self.assertEqual(len(study.trials), 1)
            self.assertEqual(run_process_mock.call_count, 3)

            run_tuning.enqueue_initial_incumbent(study, config)
            self.assertEqual(len(study.trials), 1)
            run_tuning.optimize_unique_parameter_sets(
                study,
                objective,
                all_combinations,
                requested=len(all_combinations) - 1,
                callback=lambda _study, _trial: None,
            )

        completed = run_tuning.completed_parameter_sets(study)
        duplicates = [
            trial
            for trial in study.trials
            if "duplicate_of_trial" in trial.user_attrs
        ]
        self.assertEqual(completed, all_combinations)
        self.assertEqual(len(study.trials), len(all_combinations) + 1)
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(run_process_mock.call_count, 3 * len(all_combinations))


if __name__ == "__main__":
    unittest.main()
