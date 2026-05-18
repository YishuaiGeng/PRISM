from __future__ import annotations

import prism.evaluation.benchmarks.knights_knaves as knk_module
import prism.evaluation.benchmarks.zebralogic as zebra_module
from prism.evaluation.benchmarks.knights_knaves import knk_record_to_puzzle
from prism.evaluation.benchmarks.zebralogic import zebralogic_record_to_puzzle


def test_zebralogic_hf_record_maps_to_puzzle_instance():
    record = {
        "id": "zebra_001",
        "size": "5*6",
        "puzzle": "There are five houses.\nClue 1.",
        "solution": {"nationality_Norwegian": "house1"},
        "created_at": "2026-01-01",
    }

    puzzle = zebralogic_record_to_puzzle(record)

    assert puzzle.puzzle_id == "zebra_001"
    assert puzzle.size == "5x6"
    assert puzzle.domain == "zebralogic"
    assert puzzle.nl_description == "There are five houses.\nClue 1."
    assert puzzle.solution == {"nationality_Norwegian": "house1"}
    assert puzzle.raw_data == record


def test_zebralogic_hf_record_accepts_list_solution_pairs():
    record = {
        "id": "zebra_002",
        "size": "4*5",
        "puzzle": "Puzzle text",
        "solution": [["color_blue", "house2"], ["pet_dog", "house4"]],
    }

    puzzle = zebralogic_record_to_puzzle(record)

    assert puzzle.solution == {"color_blue": "house2", "pet_dog": "house4"}


def test_knk_hf_record_maps_boolean_solution_to_roles():
    record = {
        "quiz": "A says B is a knave.",
        "names": ["A", "B"],
        "solution": [True, False],
        "solution_text": "A is a knight. B is a knave.",
        "statements": ["A says B is a knave."],
    }

    puzzle = knk_record_to_puzzle(record, split="2ppl", index=7)

    assert puzzle.puzzle_id == "knk_2ppl_7"
    assert puzzle.size == "knk_2"
    assert puzzle.domain == "knights_knaves"
    assert puzzle.nl_description.startswith("There are 2 characters.")
    assert "A says B is a knave." in puzzle.nl_description
    assert puzzle.solution == {"A": "knight", "B": "knave"}
    assert puzzle.raw_data == record


def test_knk_hf_record_handles_string_names_and_missing_statements():
    record = {
        "quiz": "Alice says Bob is a knight.",
        "names": "Alice,Bob",
        "solution": [False, True],
    }

    puzzle = knk_record_to_puzzle(record, split="2ppl", index=0)

    assert puzzle.solution == {"Alice": "knave", "Bob": "knight"}
    assert "Alice says Bob is a knight." in puzzle.nl_description


def test_load_zebralogic_hf_uses_dataset_id_and_subset(monkeypatch):
    calls = []

    def fake_load_dataset(dataset_id, subset, split):
        calls.append((dataset_id, subset, split))
        return [
            {
                "id": "zebra_003",
                "size": "3*5",
                "puzzle": "Puzzle text",
                "solution": {"x": "house1"},
            }
        ]

    monkeypatch.setattr(zebra_module, "_load_hf_dataset", fake_load_dataset)

    puzzles = zebra_module.load_zebralogic(
        "allenai/ZebraLogicBench",
        source="hf",
        subset="grid_mode",
        split="test",
        sizes=["3x5"],
    )

    assert calls == [("allenai/ZebraLogicBench", "grid_mode", "test")]
    assert len(puzzles) == 1
    assert puzzles[0].puzzle_id == "zebra_003"


def test_load_knk_hf_loads_requested_people_splits(monkeypatch):
    calls = []

    def fake_load_jsonl(dataset_id, path):
        calls.append((dataset_id, path))
        return [
            {
                "quiz": "A says A is a knight.",
                "names": ["A"],
                "solution": [True],
            }
        ]

    monkeypatch.setattr(knk_module, "_load_hf_jsonl", fake_load_jsonl)

    puzzles = knk_module.load_knights_knaves(
        "K-and-K/knights-and-knaves",
        source="hf",
        subset="test",
        people_counts=[2, 3],
    )

    assert calls == [
        ("K-and-K/knights-and-knaves", "test/people2_num100.jsonl"),
        ("K-and-K/knights-and-knaves", "test/people3_num100.jsonl"),
    ]
    assert len(puzzles) == 2
    assert {p.size for p in puzzles} == {"knk_1"}
