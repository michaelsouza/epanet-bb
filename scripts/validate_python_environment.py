#!/usr/bin/env python3
"""Audit Python dependencies and smoke-test the reproducibility environment."""

from __future__ import annotations

import argparse
import ast
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DIRECT_REQUIREMENTS = ROOT / "requirements.in"
IMPORT_TO_DISTRIBUTION = {
    "PIL": "pillow",
}
SUPPORTED_PYTHON = ((3, 11), (3, 13))


def normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_distributions(path: Path) -> set[str]:
    distributions = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None:
            raise ValueError(f"unsupported requirement in {path}: {raw_line}")
        distributions.add(normalized_distribution(match.group(1)))
    return distributions


def script_imports(directory: Path) -> set[str]:
    imports = set()
    local_modules = {path.stem for path in directory.glob("*.py")}
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
    return {
        name
        for name in imports
        if name not in sys.stdlib_module_names and name not in local_modules
    }


def audit_report() -> dict:
    imports = script_imports(ROOT / "scripts")
    direct = declared_distributions(DIRECT_REQUIREMENTS)
    distributions = {
        normalized_distribution(IMPORT_TO_DISTRIBUTION.get(name, name))
        for name in imports
    }
    return {
        "python": ".".join(map(str, sys.version_info[:3])),
        "supported_python": ">=3.11,<3.14",
        "direct_distributions": sorted(distributions),
        "undeclared_imports": sorted(distributions - direct),
        "unused_direct_distributions": sorted(direct - distributions),
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="audit script imports without running simulation and plotting smoke tests",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "python-environment-smoke",
        help="directory for the smoke-test plot and JSON receipt",
    )
    return parser.parse_args()


def run_smoke(output_directory: Path) -> dict:
    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import wntr

    network_path = ROOT / "networks" / "any-town.inp"
    network = wntr.network.WaterNetworkModel(network_path)
    with tempfile.TemporaryDirectory(prefix="epanet-bb-wntr-") as temporary:
        file_prefix = str(Path(temporary) / "simulation")
        results = wntr.sim.EpanetSimulator(network).run_sim(
            file_prefix=file_prefix
        )
    heads = results.node["head"]
    if heads.empty:
        raise RuntimeError("WNTR returned no hydraulic time steps")

    output_directory.mkdir(parents=True, exist_ok=True)
    artifact = output_directory / "environment-smoke.png"
    first_node = str(heads.columns[0])
    elapsed_hours = heads.index.to_numpy(dtype=float) / 3600.0

    figure, axis = plt.subplots(figsize=(6, 3))
    axis.plot(elapsed_hours, heads.iloc[:, 0].to_numpy())
    axis.set_xlabel("Elapsed time (h)")
    axis.set_ylabel(f"Head at node {first_node}")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    figure.savefig(artifact, dpi=120)
    plt.close(figure)

    return {
        "network": str(network_path),
        "nodes": int(heads.shape[1]),
        "time_steps": int(heads.shape[0]),
        "plotted_node": first_node,
        "artifact": str(artifact.resolve()),
        "artifact_bytes": artifact.stat().st_size,
    }


def main() -> int:
    arguments = parse_arguments()
    if not (
        SUPPORTED_PYTHON[0] <= sys.version_info[:2] <= SUPPORTED_PYTHON[1]
    ):
        print(
            "Python 3.11 through 3.13 is required",
            file=sys.stderr,
        )
        return 2

    report = audit_report()
    if report["undeclared_imports"] or report["unused_direct_distributions"]:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    if arguments.audit_only:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    report["installed_versions"] = {
        distribution: version(distribution)
        for distribution in report["direct_distributions"]
    }
    report["simulation"] = run_smoke(arguments.output_dir.resolve())
    receipt = arguments.output_dir.resolve() / "environment-smoke.json"
    receipt.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
