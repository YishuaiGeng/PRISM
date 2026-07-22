from __future__ import annotations

import json

from scripts.shared.filter_trace_subset import _selected_ids, _write_subset


def test_filter_trace_subset_selects_memory_eligible_records(tmp_path):
    trace = tmp_path / "trace.jsonl"
    data = tmp_path / "data.jsonl"
    output = tmp_path / "subset.jsonl"
    trace_records = [
        {"puzzle_id": "p1", "memory_eligible": True, "steps": []},
        {"puzzle_id": "p2", "memory_eligible": False, "steps": [{"action": "repair"}]},
        {"puzzle_id": "p3", "memory_eligible": False, "steps": []},
    ]
    data_records = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]
    _write_jsonl(trace, trace_records)
    _write_jsonl(data, data_records)

    selected = _selected_ids(trace, "memory_eligible")
    written = _write_subset(data, output, selected)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert selected == {"p1", "p2"}
    assert written == 2
    assert [row["id"] for row in rows] == ["p1", "p2"]


def _write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")
