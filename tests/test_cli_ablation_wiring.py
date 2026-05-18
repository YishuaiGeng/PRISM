from __future__ import annotations

from scripts.run_experiments import _build_solver


def test_experiment_builder_disables_memory_and_paradigm():
    solver = _build_solver(
        model_name="GPT-4o",
        library_path=":memory:",
        no_paradigm=True,
        no_memory=True,
        max_repair=2,
    )

    assert solver._enable_paradigm is False
    assert solver._enable_memory is False
    assert solver._layer2 is False


def test_experiment_builder_keeps_full_prism_by_default():
    solver = _build_solver(
        model_name="GPT-4o",
        library_path=":memory:",
    )

    assert solver._enable_paradigm is True
    assert solver._enable_memory is True
    assert solver._layer2 is True
