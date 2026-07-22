from __future__ import annotations

import scripts.prism.run_experiments as run_experiments
import scripts.prism.run_online as run_online


def test_run_online_defaults_to_hf_zebralogic_dataset():
    args = run_online.parse_args([])

    assert args.data_dir == "allenai/ZebraLogicBench"
    assert args.data_source == "auto"
    assert args.data_subset == "grid_mode"


def test_run_experiments_defaults_to_hf_dataset_ids():
    args = run_experiments.parse_args([])

    assert args.data_dir == "allenai/ZebraLogicBench"
    assert args.data_source == "auto"
    assert args.data_subset == "grid_mode"
    assert args.knk_data_dir == "K-and-K/knights-and-knaves"
    assert args.knk_data_source == "auto"
    assert args.knk_subset == "test"
