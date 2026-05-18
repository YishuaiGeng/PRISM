# PRISM: Paradigm-guided Reasoning with Iterative Solver Memory

## Project Structure

```
prism/
├── prism/                   # Core Python package
│   ├── core/                # Shared utilities and base classes
│   ├── offline/             # Offline paradigm mining pipeline
│   ├── paradigm_library/    # Paradigm storage and retrieval
│   ├── online/              # Online inference and solver loop
│   └── evaluation/          # Evaluation metrics and benchmarks
├── scripts/                 # Entry-point scripts
├── data/                    # Datasets and trajectories
├── tests/                   # Unit and integration tests
├── config/                  # Configuration files
│   └── default.yaml
└── paradigm_store/          # Persisted paradigm embeddings/metadata
```

## Setup

```bash
pip install -e .
```

## Configuration

Edit `config/default.yaml` to set your LLM backend (`anthropic` or `openai`), model name, and detection thresholds.

## Testing

```bash
pytest --cov=prism tests/
```
