from __future__ import annotations

import json

from scripts.prism.run_online import _save_trace_jsonl, parse_args


def test_run_online_schema_hint_mode_defaults_to_puzzle():
    args = parse_args([])

    assert args.schema_hint_mode == "puzzle"


def test_run_online_accepts_solution_key_schema_hint_mode():
    args = parse_args(["--schema-hint-mode", "solution_keys"])

    assert args.schema_hint_mode == "solution_keys"


def test_run_online_accepts_trace_output():
    args = parse_args(["--trace-output", "results/trace.jsonl"])

    assert args.trace_output == "results/trace.jsonl"


def test_run_online_accepts_manifest_output():
    args = parse_args(["--manifest-output", "results/run.manifest.json"])

    assert args.manifest_output == "results/run.manifest.json"


def test_run_online_accepts_translation_normalize():
    args = parse_args(["--translation-normalize", "initial"])

    assert args.translation_normalize == "initial"


def test_save_trace_jsonl_preserves_steps(tmp_path):
    path = tmp_path / "trace.jsonl"
    _save_trace_jsonl(
        [
            {
                "puzzle_id": "p1",
                "solved": False,
                "steps": [
                    {
                        "action": "repair",
                        "error_paradigms": [{"id": "e1"}],
                        "repair_response": "Int('x') > 0",
                    }
                ],
            }
        ],
        str(path),
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert rows[0]["steps"][0]["error_paradigms"][0]["id"] == "e1"
    assert rows[0]["steps"][0]["repair_response"] == "Int('x') > 0"
