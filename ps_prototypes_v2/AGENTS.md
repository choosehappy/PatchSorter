# Agent Guidelines for PatchSorter v2

> **Project context:** See [`PROJECT.md`](./PROJECT.md) for full scope, architecture, and goals.
> In short: this repo develops the core embedding + 2D layout algorithms for an active learning
> labeling tool targeting ≥1B objects. Progressive (per-batch) rendering is the critical constraint.
> The production UI, patch loading, and API layer live elsewhere.

---

## Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r tests/requirements.txt

# Lint
python3 -m ruff check .

# Format
python3 -m ruff format .

# Type check
python3 -m mypy .

# Run all tests
python3 -m pytest tests/

# Single file / function
python3 -m pytest tests/test_file.py
python3 -m pytest tests/test_file.py::test_function_name

# With coverage
python3 -m pytest --cov=src
```

**Requirements:** Python 3.8+, `torch`, `numpy`, `pandas`, `scikit-learn`, `opencv-python`, `matplotlib`, `seaborn`

---

## Code Style

- **PEP 8**; enforced by `ruff`. Let the formatter decide; don't bikeshed.
- `from __future__ import annotations` at the top of every module.
- Import order: stdlib → third-party → local, each group separated by a blank line. No wildcard imports.
- Naming: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants, `_single_underscore` for private members.
- Type hints on all public function signatures. Use `Optional[X]` / `X | None` over `Union[X, None]`. Prefer built-in generics (`list[int]`, `dict[str, Any]`) on 3.9+; use `typing.*` equivalents for 3.8 compat.
- Docstrings (NumPy style) on all public functions, classes, and modules. Comments explain *why*, not *what*.
- Use `logging` — never `print` — for debug/info output.

---

## Domain-Specific Guidelines

These rules reflect the constraints described in `PROJECT.md`.

### Embeddings & Model
- All embedding models must support **incremental / online inference**: given a new batch, produce valid 2D coordinates immediately without requiring a full-dataset pass.
- Do not design training loops that assume a complete epoch before the first output — progressive rendering requires batch-level updates.
- Seed all random ops (`torch.manual_seed`, `numpy.random.seed`) and document the seed in configs. Reproducibility is required for ablations.
- Store model checkpoints and configs together so any checkpoint is self-describing.

### Loss Functions
- Each loss component (`self_supervised`, `layout_2d`, `homogeneity`, `heterogeneity`, `supervised`) must be implemented as an independent, testable module.
- Every loss module must expose a `weight` parameter and default to a documented, justified value.
- Log each loss component's value separately per step — never only the combined total.

### Batch Pipeline
- The canonical pipeline is: **patches → embeddings → 2D coords → UI update**.
- Each stage must be independently benchmarkable.
- Batch processing must not accumulate state that grows unboundedly with dataset size.
- At epoch completion, a full redraw/re-layout is expected; design accordingly.

### Scale
- Assume ≥1B objects. Avoid `O(n²)` operations over the full dataset. Approximate algorithms are preferred over exact ones that don't scale.
- Profile before optimising; include benchmark results in PR descriptions for perf-sensitive changes.

---

## Development Workflow

1. Branch from `main`.
2. Before committing: `python3 -m ruff check . && python3 -m mypy .`
3. All tests must pass: `python3 -m pytest tests/`
4. New functionality requires unit tests. Loss components and pipeline stages require their own test files.
5. Commit messages explain *why*, not *what*. Reference `PROJECT.md` goals where relevant.

---

## Code Review Checklist

- [ ] Online/incremental compatibility — does it work without a full epoch?
- [ ] Loss components are independent and separately logged
- [ ] No unbounded memory growth at scale
- [ ] Type hints present and correct
- [ ] Tests cover edge cases (empty batch, single-item batch, label-free batch)
- [ ] Linter and formatter pass cleanly

---

## Code Review Agent Architecture

The code review system is implemented as a multi-agent architecture:

1. **Main CodeReviewAgent** - Orchestrates the entire review process
2. **RuffAgent** - Handles static code analysis using ruff 
3. **MypyAgent** - Performs type checking with mypy
4. **TestAgent** - Executes tests and reports results
5. **CoverageAgent** - Checks code coverage metrics

All agents follow a consistent pattern:
- Each agent is in its own file within `/src/` directory  
- Agents save their outputs to the same timestamped review directory under `reviews/`
- Results are structured consistently for easy parsing and reporting