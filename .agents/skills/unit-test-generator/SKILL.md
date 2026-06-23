---
name: unit-test-generator
description: Generate unit tests for PatchSorter store classes (DB layer) following project conventions. Use when asked to write tests for stores in patchsorter/db/head_client/, add tests to existing test files, or create new test modules.
---

# unit-test-generator

Generate unit tests for PatchSorter store classes with pytest against a running Citus/Postgres container.

## 1 — Orient

```bash
ls patchsorter/db/head_client/       # store classes
ls patchsorter/tests/                 # existing tests for style reference
grep -n "def " patchsorter/db/head_client/<store>.py  # methods to test
```

Key fixtures in `conftest.py`:
- **`db_session`** (session-scoped) — provides `SessionManager` connected to `patchsorter_test`
- **`session`** (function-scoped) — wrapped in a savepoint, rolled back after each test
- **`example_project`** (function-scoped) — seeds project_id=1, two label classes, one image, five patches. Tears down via `ProjectStore.delete(1)` at teardown. Returns `{"project_id": 1, "image_id": 1}`.

## 2 — Generate

**Naming:** `test_<store>_<method>_<behavior>` in `test_<store>.py`. Docstring: one-line summary of the behavior.

**Group tests** with `# --- Section header ---` comment blocks.

**Fixture strategy:**
- Use `session` (savepoint-scoped) for most tests — provides transaction isolation
- Use `example_project` when the store needs pre-seeded related data (PatchStore)
- Use `db_session` when you need the raw `SessionManager` (rare)

**Progression:**
1. Basic create/fetch
2. Bulk/copy operations
3. Update/relate operations
4. Error handling (`pytest.raises`)
5. Edge cases (empty results, missing data)

**Helpers:** File-specific `_make_*` functions for test data. Keep them private, minimal. No shared factory module.

**Assertions:** `assert result == expected_dict`, `assert len(result) == N`, `assert "key" in result`, `assert result["key"] == value`, `assert result is None`, `with pytest.raises(X, match="pattern"):`.

**Key store quirks:**
- `PatchStore(project_id, session)` — takes project_id at construction, not session
- `ConfusionMatrixStore(project_id, level, session)` — three args
- `LabelClassStore.delete()` raises `ValueError` if deleting `label_class_id=1` (reserved Unlabeled)
- `ProjectStore.create()` auto-seeds settings — don't test settings separately after create
- `SettingsStore.update()` validates against `settings_defaults.toml` — test both valid and invalid values

## 3 — Run

```bash
pytest patchsorter/tests/ -v
pytest patchsorter/tests/test_<store>.py -v
pytest patchsorter/tests/test_<store>.py::test_<store>_<method>_<behavior> -v
```

## 4 — Verify

```bash
pytest patchsorter/tests/test_<store>.py -v   # must pass
```

Checklist:
- All tests pass
- Naming matches `test_<store>_<method>_<behavior>`
- Docstrings describe behavior, not implementation
- Section headers (`# ---`) group related tests
- No `pytest.mark.parametrize` — use separate functions
- No new shared utilities — helpers stay file-local
- Constructor args match actual store signatures (PatchStore takes project_id!)

## 5 — Summarise

Report: store tested, methods covered, tests generated, pass/fail result.
