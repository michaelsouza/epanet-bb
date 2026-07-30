# Experiment and manuscript tooling

Most users need only two entry points:

- `run_campaign.py` plans, executes, or resumes experiment subsets declared in
  `experiments/reproducibility.json`, including `--select ablation` and
  `--select scalability`.
- `rebuild_manuscript.py` reconstructs the declared manuscript products from
  checked-in data without running MPI experiments.

The remaining scripts are implementation components called by those workflows
or focused provenance utilities:

- Campaign execution: `run_experiments.py`, `run_tuning.py`, and
  `run_accuracy_sensitivity.py`.
- Result processing: `summarize_ablation.py`, `summarize_scalability.py`,
  `summarize_final_cases.py`, `summarize_accuracy_sensitivity.py`,
  `audit_accuracy_sensitivity.py`, `evaluate_comparison_schedules.py`, and
  `prepare_manuscript_artifacts.py`.
- Figure generation: `create_comparison_table_images.py`, `plot_network.py`,
  `plot_scalability.py`, `plot_tanks.py`, `plot_tree_decomposition_diagram.py`,
  and `plot_two_level_diagram.py`.
- Environment validation: `validate_python_environment.py`.

