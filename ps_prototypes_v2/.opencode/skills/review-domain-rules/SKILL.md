# Skill: review-domain-rules

PatchSorter v2 domain-specific review rules. These extend general code quality checks
and are derived from PROJECT.md and AGENTS.md. Apply these on top of all other review criteria.

## Pipeline Contract

The canonical pipeline is strictly ordered:

```
patches → embeddings → 2D coords → UI update
```

**Rules:**
- Each stage must be an independently callable and benchmarkable unit.
- No stage may depend on the completion of a full epoch before producing output.
- The 2D coord stage must emit coordinates for each incoming batch immediately.
- UI update events must be fired per batch, not per epoch.

## Online / Incremental Inference

The embedding model and 2D projection **must** support online inference:

- Given a new batch of patches, produce valid 2D coordinates immediately.
- The model may continue to improve with more data, but must never block output.
- Flag any code path where `fit()`, `transform()`, or equivalent is called on the full dataset before the first coordinate is emitted.
- Acceptable patterns: online PCA, incremental UMAP variants, streaming t-SNE approximations, learned projectors updated per batch.
- Unacceptable patterns: standard sklearn `UMAP.fit_transform(all_data)`, `TSNE.fit_transform(all_data)`.

## Loss Function Architecture

Five named components, each independently implemented:

| Name | Key requirement |
|---|---|
| `self_supervised` | Must function with zero labels |
| `layout_2d` | Operates in 2D projection space; encourages well-structured layout |
| `homogeneity` | Pulls same-class or similar patches together |
| `heterogeneity` | Pushes different-class or dissimilar patches apart |
| `supervised` | Only active when labels are present; strong pull toward class structure |

**Rules for every loss module:**
- Exposed as an importable class or function with a `weight: float` parameter.
- Default weight must be documented with a justification (empirical or theoretical).
- Returns a scalar tensor — never a tuple or dict (combine at the call site).
- Logged individually every step via the project logger; combined total also logged separately.
- Must handle the label-free case gracefully (return 0.0 or skip, never crash).
- Must handle edge cases: empty batch, single-item batch, all-same-class batch.

## Active Learning Integration

- Label events from the UI drive updates to both embedding space and prediction space.
- The supervised loss weight should increase (or activate) when labels are present.
- Any logic gating on label availability must be explicit and testable in isolation.

## Test Requirements (Domain-specific)

Every loss module test file must include:
- `test_<name>_no_labels` — verifies graceful handling when no labels are provided
- `test_<name>_empty_batch` — verifies no crash on zero-length input
- `test_<name>_single_item` — verifies no crash or NaN on batch size 1
- `test_<name>_all_same_class` — verifies finite, non-NaN output
- `test_<name>_gradient_flow` — verifies `loss.backward()` produces non-zero, finite gradients
- `test_<name>_weight_zero` — verifies that `weight=0.0` produces exactly 0.0 loss contribution

Pipeline stage tests must include a `benchmark_` fixture (pytest-benchmark or equivalent) to catch performance regressions.
