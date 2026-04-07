# Skill: review-scalability-lens

Patterns to actively look for when reviewing code at ≥1B object scale.
Flag every occurrence as a Scalability finding with the appropriate severity.

## Critical Patterns (CRITICAL / HIGH)

| Pattern | Why it fails at scale | Suggestion |
|---|---|---|
| `O(n²)` loop or pairwise distance over full dataset | 1B² ops — completely infeasible | Use ANN (FAISS, ScaNN, hnswlib) or minibatch approximations |
| Collecting all embeddings into a single in-memory tensor/list | 1B × D floats → hundreds of GB RAM | Stream or shard; use memory-mapped arrays (numpy memmap, HDF5) |
| `model.fit(full_dataset)` or similar full-pass requirement before any output | Blocks progressive rendering | Redesign as online/incremental; emit per-batch |
| Exact kNN over full dataset | O(n·d) per query, n=1B | Replace with FAISS IVF or HNSW index |
| Storing per-object state in a Python `dict` or `list` that grows per batch | Unbounded RAM | Use fixed-size buffers, reservoirs, or on-disk stores |

## Medium Patterns (MEDIUM)

| Pattern | Why it matters | Suggestion |
|---|---|---|
| Missing `torch.no_grad()` during inference | Builds autograd graph unnecessarily, wastes memory | Wrap all inference calls in `with torch.no_grad():` |
| DataLoader missing `num_workers` > 0 | CPU bottleneck at high throughput | Set `num_workers` to number of CPU cores (typically 4–8) |
| DataLoader missing `pin_memory=True` | Slower host→GPU transfers | Enable when using CUDA |
| DataLoader missing `prefetch_factor` | Stalls GPU between batches | Set `prefetch_factor=2` or higher with `num_workers > 0` |
| Redundant recomputation of embeddings already seen | Wasted GPU cycles | Cache to disk or use a feature store |
| Synchronous logging inside the hot training loop | I/O blocks training | Use async logging or queue-based handler |
| Python-level loops over batch elements | Bypasses vectorisation | Rewrite as tensor ops |

## Low / Info Patterns (LOW / INFO)

| Pattern | Note |
|---|---|
| Mixed precision not used | `torch.autocast` can give 2× throughput on modern GPUs |
| Gradient checkpointing not used for large models | Trades compute for memory at scale |
| No benchmark/profiling fixture for the stage | Makes it impossible to detect regressions |
| `shuffle=True` on a dataset too large to fit in RAM | Requires a distributed shuffle strategy |

## Output Format

For each flagged pattern, produce a finding in the standard format:

```
### [SEVERITY] <pattern name>
**File:** `...` **Line:** N
**Category:** Scalability
**Detail:** <what was found and why it fails at 1B scale>
**Suggestion:** <concrete fix>
```

Collect all scalability findings into the **Scalability & Efficiency Highlights** section of the report, ordered by severity.
