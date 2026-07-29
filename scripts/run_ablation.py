#!/usr/bin/env python3
"""Compatibility entry point for the ablation campaign subset."""

from __future__ import annotations

import sys

from run_campaign import main


if __name__ == "__main__":
    raise SystemExit(main(["--select", "ablation", *sys.argv[1:]]))
