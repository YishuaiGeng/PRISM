from __future__ import annotations

import json

from scripts import download_datasets


def test_write_jsonl_creates_parent_and_writes_records(tmp_path):
    output = tmp_path / "nested" / "records.jsonl"

    count = download_datasets.write_jsonl(output, [{"a": 1}, {"b": 2}])

    assert count == 2
    lines = output.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"b": 2}]


def test_download_zebralogic_writes_hf_snapshot(tmp_path, monkeypatch):
    def fake_load(dataset_id, subset, split):
        assert dataset_id == "allenai/ZebraLogicBench"
        assert subset == "grid_mode"
        assert split == "test"
        return [{"id": "z1"}, {"id": "z2"}]

    monkeypatch.setattr(download_datasets, "load_hf_dataset", fake_load)

    written = download_datasets.download_zebralogic(tmp_path, max_rows=1)

    assert written == {"grid_mode_test": 1}
    output = tmp_path / "zebralogic" / "grid_mode_test.jsonl"
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8").splitlines()[0]) == {"id": "z1"}


def test_download_knk_writes_selected_splits(tmp_path, monkeypatch):
    def fake_load(dataset_id, path):
        assert dataset_id == "K-and-K/knights-and-knaves"
        return [{"path": path}, {"path": path}]

    monkeypatch.setattr(download_datasets, "load_hf_jsonl", fake_load)

    written = download_datasets.download_knights_knaves(
        tmp_path,
        people_counts=[2, 3],
        max_rows=1,
    )

    assert written == {"test_people2": 1, "test_people3": 1}
    assert (tmp_path / "knights-and-knaves" / "test_people2.jsonl").exists()
    assert (tmp_path / "knights-and-knaves" / "test_people3.jsonl").exists()
