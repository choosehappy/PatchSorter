# Deep Learning Module Integration Plan
Summary:
The purpose of this plan is to update the Deep Learning module to:
1. Use dataloaders rather than iterable python classes within the ray train loop.
2. Add a dataloader responsible for enriching the batch with labeled examples.
3. The enriched dataloader should draw from a candidate pool which gets depleted and refreshed.
4. The batches drawn from these two dataloaders should be concatenated on GPU.
5. Update loss functions to match the prototype (SwAV, adaptive pseudo-labels, rank uniform loss).
6. Change the unassigned label class ID from 1 to -1 and update the label_class autoincrement sequence. 

## Source Files

| Prototype | Location |
|-----------|----------|
| `start_v3.py` | `ps_prototypes_v2/start_v3.py` (PyTables-based baseline) |
| `start_v4_sqlite.py` | `ps_prototypes_v2/start_v4_sqlite.py` (SQLite + candidate pool enrichment) |
| `sqlite_dataset.py` | `ps_prototypes_v2/sqlite_dataset.py` |
| `utils.py` | `ps_prototypes_v2/utils.py` (SwAV loss, adaptive threshold, scoring, LabeledRateTracker) |
| `configs.py` | `ps_prototypes_v2/configs.py` |

| Production | Location |
|------------|----------|
| `losses.py` | `patchsorter/dl/losses.py` |
| `training.py` | `patchsorter/dl/training.py` |
| `model.py` | `patchsorter/dl/model.py` |
| `augmentations.py` | `patchsorter/dl/augmentations.py` |

---

## 1. Differences: `start_v4_sqlite.py` vs `start_v3.py`

### 1.1 Database backend
- **v3**: PyTables (`.pytable`) via `tables` library with custom `Dataset` class
- **v4**: SQLite with `SQLiteDataset`, `GTCandidatePool`, `CandidatePoolIterableDataset`, `ScoreWriter`

### 1.2 Candidate pool enrichment (new in v4)
- `GTCandidatePool` (line 172, `sqlite_dataset.py`) — in-memory candidate pool with decayed rarity scoring
- `CandidatePoolIterableDataset` (line 321, `sqlite_dataset.py`) — `IterableDataset` that yields enriched batches from the candidate pool
- Priority column (format `XX.YY`): XX = iteration count (times seen), YY = decayed rarity score (replaces `score_timestamp`)
- Partial index on `priority` where `priority > 0` (line 102-108, `sqlite_dataset.py`)
- `ScoreWriter` for writing scores back to the database

### 1.3 Loss function changes
| Aspect | v3 | v4 |
|--------|----|----|
| Embedding loss | `simclr_loss()` or `swav_loss()` (configurable via `LOSS_TYPE`) | `swav_loss()` always (config removed, SwAV is now canonical) |
| MMD loss | `max_mean_discrepancy()` with `MAX_MEAN_LOSS` weight | Removed — `max_mean_discrepancy()` and its weight constant are dropped from the training loop; the function may remain in `losses.py` for now but is no longer called |
| New loss | — | `rank_uniform_loss()` with `RANK_UNIFORM_LOSS` weight |
| Pseudo-label loss | `prediction_loss_pseudo()` (majority vote + fixed threshold) | `prediction_loss_pseudo_sce_adaptive()` (adaptive per-class threshold + SCE loss) |

### 1.4 Label tracker update scope fix
- **v3** line 363: `label_tracker.update(labels, ...)` — passes ALL labels including view repetitions
- **v4** line 394: `label_tracker.update(labels[0:nbase_ids], ...)` — passes only base batch labels (first view per patch)
- Pseudo labels filtered through `high_conf` mask before passing to tracker

### 1.5 View reconstruction bug fix (line 295)
- **v3** line 274: `torch.stack(views_gpu, dim=1).flatten(0, 1)` — wrong axis, produces `[B, V, ...]`
- **v4** line 295: `torch.stack(views_gpu, dim=0).flatten(0, 1)` — correct, produces `[V, B, ...] → [V*B, ...]`

This is the critical fix for labels from different views. The flattened layout must be `[V*B, ...]` (views-major) for losses like `simclr_loss` and `semantic_head_loss` that operate on the flat tensor with `labels.repeat(V)`.

### 1.6 Score computation (new in v4)
- `compute_weighting_scores()` (line 1470, `utils.py`) — combines spatial rarity (kNN distance in embedding space) with class rarity weights
- `ScoreWriter.enqueue()` writes `XX(niter_total).YYY(score)` format to `priority` column
- Only first-view base batch items scored (`nbase_ids`), not enriched candidates
- **Bug in prototype** (`start_v4_sqlite.py:400`): `compute_weighting_scores(ids, labels, proj_emb, ..., len(ids))` passes `len(ids)` as the count, but only the first `nbase_ids` elements of `ids`/`proj_emb` are from the sequential batch. The correct call is `compute_weighting_scores(ids, labels, proj_emb, ..., nbase_ids)`. This must be fixed in the production implementation.

### 1.7 Adaptive threshold (new in v4)
- `AdaptiveThreshold` class (line 1396, `utils.py`) — FlexMatch-style per-class adaptive thresholding
- Tracks `sigma_c` (EMA of per-batch crossing counts) for each class
- `high_conf_mask()` applies per-class thresholds to majority-vote confidence

---

## 2. Database Changes

### 2.1 Partial index on train_priority column

**Purpose**: Rapid selection of rare/labeled patches for training enrichment.

**Naming note**: The DL rarity-scoring column is named `train_priority`, not `priority`. The name `priority` is already used elsewhere in the codebase for an unrelated concept — a computed value (1 = from `pred_patch_latest`, 2 = from `pred_patch_last`) indicating prediction-source precedence, returned by `PatchStore._paginated_pred_join()` (`patchsorter/db/head_client/patch.py`) and also exposed through the API (`priority?: number` in `types.gen.ts`). Reusing `priority` for the new column would collide with this existing field.

**Proposed index**:
```sql
CREATE INDEX idx_patches_train_priority_positive
ON patches (train_priority)
WHERE train_priority > 0;
```

**Notes**:
- The prototype's partial index on `score_timestamp` (line 102-108, `sqlite_dataset.py`) shows the pattern — this will be migrated to `train_priority`

### 2.2 Partial index on ground truth label column

**Purpose**: Rapid selection of labeled patches for training enrichment.

**Proposed index**:
```sql
CREATE INDEX idx_patches_gt_label_positive
ON patches (label_class_id)
WHERE label_class_id > 0;
```

**Notes**:
- The prototype creates this on `tmp_label` where `tmp_label > -1` (line 109-115, `sqlite_dataset.py`)
- After §2.4, the unassigned class has ID `-1` and user classes start at `0`, so `WHERE label_class_id > 0` excludes both unassigned and the class at index 0
- If class 0 should be included, use `WHERE label_class_id >= 0` instead
- Paired with the `train_priority` partial index (§2.1) to support fast enrichment queries for labeled patches

### 2.3 train_priority column on patch table

**Format**: `XX.YY`
- `XX` — integer: number of times the patch has been sampled for training
- `YY` — float in `[0, 1]`: patch weighting (rarity score)

**Implementation**: Add `train_priority` column to the dynamic patch model in `patchsorter/db/head_client/models.py:148-167`.

**Action**: Add to the `patch_model()` function's column dict:
```python
"train_priority": Column(Float, nullable=True),
```

**Notes**:
- `train_priority` replaces `score_timestamp` from the prototype
- Named `train_priority` (not `priority`) to avoid colliding with the existing prediction-source `priority` field described in §2.1
- No `ALTER TABLE` migration needed — the column is defined in the ORM model
- Update interval: per-batch (like prototype)

### 2.4 Label class autoincrement — unassigned class ID change to -1

**Current state**: The "Unassigned" / "Unlabeled" class has `label_class_id = 1` (positive integer).

**Current seeding** (`database_manager.py:93-97`):
```sql
INSERT INTO label_class (project_id, name, color_code)
SELECT NULL, 'unassigned', NULL
WHERE NOT EXISTS (SELECT 1 FROM label_class WHERE label_class_id = 1);
```

**Current constant** (`config/constants.py:41`):
```python
UNASSIGNED_CLASS_ID = 1
```

**Current model** (`models.py:90`):
```python
label_class_id = Column(Integer, primary_key=True, autoincrement=True)
```

**Changes required**:

1. **`UNASSIGNED_CLASS_ID`** in `config/constants.py`: Change from `1` to `-1`
2. **Seeding SQL** in `database_manager.py:93-97`: Change `label_class_id = 1` to `label_class_id = -1`
3. **`label_class_id` column** in `models.py:90`: Remove `autoincrement=True` — the unassigned class gets an explicit ID of -1, and subsequent classes autoincrement from there. The sequence must start at 0 so the first user-created class gets ID 0, then 1, 2, ...
   ```python
   label_class_id = Column(Integer, primary_key=True)
   ```
4. **Sequence initialization**: After `create_all()`, ensure the sequence is set to start at 0:
   ```sql
   SELECT setval(pg_get_serial_sequence('label_class', 'label_class_id'), 0, false);
   ```
   This ensures user-created classes get IDs 0, 1, 2, ... while -1 is reserved for unassigned.
5. **`LabelClassStore.delete()`** in `label_class.py:164`: Update the guard from `UNASSIGNED_CLASS_ID == 1` to `UNASSIGNED_CLASS_ID == -1` (constant reference, so no code change needed if the constant is updated)
6. **All references to `label_class_id == 1`** across the codebase must be audited and updated to use `UNASSIGNED_CLASS_ID` or `-1` as appropriate. Key locations:
   - `database_manager.py:97` — seeding SQL
   - `database_manager.py:96` — project_id is NULL (global unassigned class)
   - `label_class.py:139` — docstring referencing `label_class_id = 1`
   - `label_class.py:164` — `UNASSIGNED_CLASS_ID` reference (uses constant, no change needed)
   - `label_class.py:174,183,193,199` — `UNASSIGNED_CLASS_ID` references (uses constant, no change needed)
   - `image.py:165` — `label_class_id = 1` reset (should use `UNASSIGNED_CLASS_ID`)
   - `training.py:152` — docstring `Returns 1 (unassigned)` — update to `-1`
   - `training.py:91` — docstring `label_class_id == 1` — update to `UNASSIGNED_CLASS_ID`
   - `training.py:129` — `to_model_index()` docstring references to unassigned class ID
   - Line numbers above reflect HEAD as of this update — commit `a3c1f6bdaac7db18d596d9454cdb8fc17cfb7926` (DL actor/freeze-control merge) shifted several of them from the original plan draft; re-verify against HEAD before editing
7. **`training.py:LabelMap`**: The `to_model_index()` method already handles `None` and `UNASSIGNED_CLASS_ID` via the constant. After the constant change, `from_model_index()`'s fallback default (`training.py:144`, returns `UNASSIGNED_CLASS_ID`) will return `-1` instead of `1` — this is correct behavior for the model output.

**Notes**:
- Using `-1` for unassigned aligns with the prototype's `tmp_label > -1` convention
- Positive IDs (0, 1, 2, ...) for user classes simplify the partial index in §2.2 (`WHERE label_class_id > 0`)
- The autoincrement sequence must be carefully managed to avoid collisions with the reserved -1 value
- Existing databases will need a migration script to update `label_class_id = 1` → `-1` for the unassigned row, and update all foreign key references in `patches`, `pred_patch_latest`, `pred_patch_last`, and confusion matrix tables
- For the development instance (recreated after schema update), no migration is needed

---

## 3. Dataloader Design

**Architecture requirement**: Both dataloaders must be implemented as genuine
`torch.utils.data.IterableDataset` subclasses wrapped in a
`torch.utils.data.DataLoader` — not consumed as plain Python iterables
in-process, which is how the current `ShardDataset` works
(`patchsorter/dl/training.py:182-222`, consumed via a bare `for ... in
ShardDataset(...)` loop inside `train_worker`). Moving to a real
`IterableDataset` + `DataLoader` pushes CPU-bound work (DB fetch, image
decode, NVIEWS augmentation) off the main GPU training loop and into
`DataLoader` worker processes, which prefetch concurrently with the
backbone/joint_head forward-backward pass.

### 3.1 `dataloader_sequential`

**Source**: `IterableShardDataset(torch.utils.data.IterableDataset)` (new class,
replaces the current plain-iterable `ShardDataset`)

**Behavior**:
- Iterates sequentially through worker-assigned shards
- No enrichment, no candidate pool
- Used for prediction saving (only sequential part of batch is saved)
- Iterated until exhausted at the start of each cycle

**Implementation approach**:
- Replace `ShardDataset` with `IterableShardDataset`, subclassing
  `torch.utils.data.IterableDataset`. Move the DB session/cursor/fetch logic
  currently in `ShardDataset.__iter__` **and** the image-decode
  (`_decode_patch_image`) + NVIEWS augmentation construction currently
  inline in `train_worker`'s for-loop (`training.py` ~lines 390-401) into
  this dataset's `__iter__`, so each yielded item is already a decoded,
  augmented CPU tensor ready for `.to(device)`.
- Each Ray Train worker still gets a deterministic shard subset via
  `compute_shard_assignments()` (unchanged — first level of sharding).
- Within a single Ray Train worker, use `torch.utils.data.get_worker_info()`
  inside `__iter__` to partition that worker's `assigned_shards` across the
  `DataLoader`'s own worker processes (second level of sharding) — required
  whenever `num_workers > 1`, to avoid duplicate or missing shards.
- Wrap in `DataLoader(IterableShardDataset(...), batch_size=None,
  num_workers=N, multiprocessing_context="spawn", worker_init_fn=...,
  persistent_workers=True)`. `batch_size=None` because the dataset yields
  pre-collated, already-augmented batches directly, matching the existing
  DB-side batching (`fetch_patch_batch`).
- **Session/process safety**: Use `multiprocessing_context="spawn"` (not the
  default `"fork"`) to avoid inheriting live socket/connection file
  descriptors from the parent process. `worker_init_fn` calls a new
  `dispose_engine()` helper (add to `patchsorter/db/utils.py`, e.g.
  `SessionManager.dispose_engine()` wrapping SQLAlchemy's
  `self.engine.dispose()`) so each spawned worker drops any
  pickled/reconstructed engine's inherited connection pool and lazily opens
  fresh connections on first use inside `__iter__`. The dataset must hold
  raw connection parameters (or call `worker_client.get_client()` fresh
  inside `__iter__`), not a live `SessionManager`/engine, to remain
  picklable under `spawn`.
- **Augmentation determinism across workers**: `worker_init_fn` must also
  reseed NumPy/Python RNGs per worker (e.g. via `torch.initial_seed()` /
  `worker_info.seed`) — otherwise Albumentations' NumPy-based randomness in
  `get_transforms()` (`patchsorter/dl/augmentations.py`) will produce
  identical augmentations across workers. Re-instantiate
  `get_transforms(patch_size)` once per worker inside `__iter__` rather than
  passing pre-built transform objects through `__init__`.
- **Further consideration**: size `num_workers` from the per-worker CPU
  allocation Ray Train grants each process (via `app_config` / Ray resource
  spec), not a hardcoded constant.
- `train_worker`'s main loop changes accordingly: replace
  `dataset = ShardDataset(...)` and the inline decode/augment block with
  `sequential_loader = DataLoader(IterableShardDataset(...), batch_size=None, num_workers=...)`,
  iterating pre-augmented CPU tensors and moving only `.to(device)` into the
  main process.

### 3.2 `dataloader_enriched`

**Source**: `EnrichedInfiniteIterableDataset(torch.utils.data.IterableDataset)`
(new class, based on `CandidatePoolIterableDataset` in `sqlite_dataset.py`)

**Behavior**:
- Uses in-memory `CandidatePool` with candidate scores
- Infinite iteration with periodic pool refresh
- Draws batches weighted by candidate score (rarity)
- Decays in-memory scores after each draw
- **Waits for ground truth labels before enrichment begins** (see §3.2.1)

**Implementation approach**:
- `EnrichedInfiniteIterableDataset` subclasses `torch.utils.data.IterableDataset`,
  following the same pattern as `IterableShardDataset` (§3.1).
- Each `DataLoader` worker process owns its own `CandidatePool` (in-memory)
  + PostgreSQL worker-client connection, both created lazily inside
  `__iter__` (never in `__init__`, for the same fork/spawn-safety reasons
  as §3.1).
- Pool refreshes every N batches from PostgreSQL via manual UNION across
  shards (not Citus) with `ORDER BY train_priority` + `LIMIT`.
- Wrapped in `DataLoader(dataset, batch_size=None, num_workers=N,
  multiprocessing_context="spawn", worker_init_fn=...,
  persistent_workers=True)` — the same `spawn` + `dispose_engine()` +
  RNG-reseeding requirements from §3.1 apply here.

**Backend**: Production uses PostgreSQL via the worker client (not SQLite). The prototype's `sqlite_dataset.py` pattern informs the design but the implementation queries PostgreSQL directly.

**Sharding note**: The enriched dataloader must query across Citus shards. Since Citus does not support `ORDER BY` + `LIMIT` across shards efficiently, the UNION must be performed manually on PostgreSQL (not through Citus). Each shard is queried separately and results merged client-side. **Critical**: The CandidatePool's union operation MUST union across only the shards that were made available to the worker for training (per `compute_shard_assignments()`), not the global list of all shards. The respective database queries must use `worker_client` (not `head_client`) to access those worker-assigned shards.

#### 3.2.1 Label-waiting mechanism

**Problem**: The candidate pool is populated from patches with ground truth labels. At training start, no labels may exist yet (project just created, user hasn't labeled anything). Drawing from an empty pool wastes compute cycles.

**Solution**: Each `EnrichedInfiniteIterableDataset` instance checks periodically whether any labeled patches exist in the database before drawing from the pool.

- **`CandidatePool.has_labels()`** — new method that queries the database for `SELECT EXISTS(SELECT 1 FROM patches WHERE label_class_id > 0 LIMIT 1)`. Returns `True` if any labeled patch exists.
- **Check frequency**: Every N batches (configurable via `GT_LABEL_CHECK_INTERVAL`, default 10 batches)
- **Behavior when no labels**: Yield `None` or skip enrichment for that batch (sequential-only training)
- **Behavior when labels found**: Begin normal enrichment flow — load candidate pool and draw batches
- **Once labels exist**: No further checks needed for the lifetime of the pool (optimization: skip subsequent checks after first positive)

**Implementation in `EnrichedInfiniteIterableDataset.__iter__`**:
```python
batches_since_check = 0
labels_confirmed = False

while True:
    if not labels_confirmed:
        batches_since_check += 1
        if batches_since_check >= GT_LABEL_CHECK_INTERVAL:
            labels_confirmed = self.pool.has_labels()
            if labels_confirmed:
                self.pool.refresh()  # Load initial candidate pool
            batches_since_check = 0
    
    if not labels_confirmed:
        yield None  # Skip enrichment, sequential-only batch
        continue
    
    picks = self.pool.draw_batch(batch_size)
    yield self._collate_from_picks(picks)
```

### 3.3 Training loop structure

This restructuring replaces the `TODO: Selective training loop` placeholder
already present in `train_worker` (`patchsorter/dl/training.py` ~lines
344-353) together with the inline `ShardDataset` iteration below it.

```
# Outside cycle loop:
sequential_loader = DataLoader(IterableShardDataset(...), batch_size=None, num_workers=N,
                                multiprocessing_context="spawn", worker_init_fn=...)
enriched_loader = DataLoader(EnrichedInfiniteIterableDataset(...), batch_size=None, num_workers=N,
                              multiprocessing_context="spawn", worker_init_fn=...)
enriched_iter = iter(enriched_loader)

# Inside cycle loop:
for i, finite_batch in enumerate(sequential_loader):  # stops when exhausted
    if i % POLL_FROZEN_EVERY_N_BATCHES == 0:
        wait_for_unfreeze(actor)
        if ray.get(actor.get_termination_signal.remote()):
            return
    infinite_batch = next(enriched_iter)  # may be None while waiting for labels
    if infinite_batch is not None:
        batch = concat_batches(finite_batch, infinite_batch)
    else:
        batch = finite_batch  # sequential-only
    loss = model(batch)
    loss.backward()
    optimizer.step()
    optimizer.zero_grad()
```

**Enriched batch size**: Controlled by `GT_ENRICHMENT = 0.10` — the enriched dataloader yields approximately 10% of the sequential batch size.

**Key design decisions**:
- Enriched dataloader instantiated outside sequential loop (as specified) to maintain pool state
- Each training batch = concatenation of sequential + enriched (or sequential-only while waiting for labels)
- Only sequential part saved to predictions (per spec)
- Only base (sequential) batch labels update the label weight tracker — `labels[0:nbase_ids]` — matching `start_v4_sqlite.py:395`. In production this maps to the existing `raw_labels` tensor (`training.py:457`), which must remain scoped to the sequential-only batch once enrichment is added (see §5.1)
- Both parts contribute to loss computation and backprop
- **Label waiting**: Enrichment begins only after `CandidatePool.has_labels()` confirms ground truth labels exist in the database
- **Freeze/termination polling**: The enriched loop must observe the same freeze/terminate control flow as the sequential loop — call `wait_for_unfreeze(actor)` and check `actor.get_termination_signal.remote()` at the same `POLL_FROZEN_EVERY_N_BATCHES` cadence (already implemented for the sequential path at `training.py:342-353`), so both loops stay in sync with `DLActor` state

---

## 4. Loss Function Updates

### 4.1 SwAV loss — rename and replace

**Current state**: `losses.py` line 14 has `simclr_loss()` which is NT-Xent (SimCLR). In the prototype, `LOSS_TYPE` was removed and the training loop was updated to always call `swav_loss()`, but `simclr_loss` was never renamed in the prototype's `utils.py`. The function at `utils.py:1191` is the true SwAV implementation (Sinkhorn prototype assignments) and is a different algorithm from NT-Xent.

**Action**: In production `losses.py`, rename `simclr_loss()` to `swav_loss()` and **replace its implementation** with the SwAV computation from `ps_prototypes_v2/utils.py:1191`. The NT-Xent implementation is no longer used.

**Scope**: SwAV is applied only to **embedding coordinates** (`proj_emb`). The production `training.py` also computes `simclr_coord_loss = simclr_loss(proj_coords, ...)` (NT-Xent on 2D projection coordinates) — this term is **removed entirely**. The prototype already comments this out (`start_v4_sqlite.py:357`: `#simclr_emb_loss_coord = swav_loss(proj_coords)  -- this seems crazy`). The corresponding `SIMCLR_EMB_LOSS * simclr_coord_loss` term is dropped from `total_loss`.

**Considerations**:
- The new `swav_loss()` accepts a `prototypes` parameter (learnable prototypes from `JointHead`) — add `prototypes` attribute to `JointHead` model
- Add `prototypes` as a `nn.Parameter` in `JointHead.__init__()` with initialization via `_init_weights()`: small normal init followed by `F.normalize(..., dim=1)` (unit-sphere constraint)
- Prototype normalization must be re-applied after each optimizer step (normalize `model.head.prototypes.data` in the training loop)
- SwAV parameters from `configs.py`: `SWAV_PROTOTYPES=300`, `SWAV_KMEANS_ITERS=10`, `SWAV_SINKHORN_ITERS=3`, `SWAV_EPS=0.05`, `temp=0.1`
- **Implementation**: Copy `swav_loss()` from `ps_prototypes_v2/utils.py:1191` as-is. Keep `SWAV_KMEANS_ITERS` as a variable (no need to re-implement k-means logic — the prototype's k-means initialization is sufficient).

### 4.2 `prediction_loss_pseudo_sce_adaptive` — integrate

**Current state**: `losses.py` has `prediction_loss_pseudo()` (majority vote + fixed threshold + standard CE).

**Action**: Add `prediction_loss_pseudo_sce_adaptive()` from `ps_prototypes_v2/utils.py:1331` to `losses.py`.

**Key differences from existing**:
- Uses `AdaptiveThreshold` for per-class confidence thresholds instead of fixed `pseudo_thresh`
- Uses SCE loss (symmetric cross-entropy) instead of standard CE
- Requires `num_classes` parameter (uses `N_CLASS` from configs)

### 4.3 `rank_uniform_loss` — add

**Action**: Add `rank_uniform_loss()` from prototype to `losses.py`.

**Current state**: Not present in `losses.py`. The prototype uses it with weight `RANK_UNIFORM_LOSS = 10_000.0`.

### 4.4 Loss weight parameters

All production constants in `training.py` must be updated to exactly match `ps_prototypes_v2/configs.py`. These values have been carefully tuned in the prototype and should be preserved as-is. The table below shows the full migration, including renames, value changes, and removals.

| Current production | Current value | Target constant | Target value | Action |
|--------------------|---------------|-----------------|--------------|--------|
| `SIMCLR_EMB_LOSS` | 100.0 | `SWAV_EMB_LOSS` | 100 | rename |
| `MAX_MEAN_LOSS` | 1000.0 | — | — | remove (MMD dropped) |
| `COORD_CONTRASTIVE_LOSS` | **1.0 (active)** | `COORD_CONTRASTIVE_LOSS` | **0** | value change — set to 0 to match prototype |
| `SEMANTIC_LAMBDA` | 1.0 (shared) | `SEMANTIC_COORD_LAMBDA` | 1.0 | split into two constants |
| `SEMANTIC_LAMBDA` | 1.0 (shared) | `SEMANTIC_EMB_LAMBDA` | **10.0** | split — emb weight is 10× higher than prod |
| `PRED_LAMBDA` | **100.0** | `PRED_SUP_LAMBDA` | **10_000.0** | rename + 100× increase |
| `PSEUDO_PRED_LAMBDA` | **0.4** | `PSEUDO_PRED_LAMBDA` | **0.0001** | value change (intermediate factor) |
| (new) | — | `PRED_PSEUDO_LAMBDA` | `PRED_SUP_LAMBDA × PSEUDO_PRED_LAMBDA = 1.0` | derived constant for pseudo loss term |
| `COORD_CONSISTENCY_LOSS` | 1.0 | `COORD_CONSITENCY_LOSS` | 1.0 | no change (keep prototype spelling) |
| (new) | — | `RANK_UNIFORM_LOSS` | 10_000.0 | new |
| `NEIGHBOR_LAMBDA` | 0.5 | `NEIGHBOR_LAMBDA` | 0.5 | no change |
| `REPULSION_LAMBDA` | 0.1 | `REPULSION_LAMBDA` | 0.1 | no change |

**Loss computation structure** also changes. The production training loop currently combines supervised and pseudo losses before weighting:
```python
# Current production
pred_loss = sup_loss + PSEUDO_PRED_LAMBDA * pseudo_loss
total_loss += PRED_LAMBDA * pred_loss
```
The prototype applies separate top-level weights to each, matching the table above:
```python
# Target (prototype structure)
total_loss += PRED_SUP_LAMBDA * sup_pred_loss + PRED_PSEUDO_LAMBDA * pseudo_pred_loss
```
The `total_loss` computation in `training.py` must be updated to match the prototype's structure exactly (with stale `simclr`/`SIMCLR_EMB_LOSS` variable names replaced by `swav`/`SWAV_EMB_LOSS`).

---

## 5. Label Weight Tracker — `LabeledRateTracker`

### 5.1 Differences from `losses.py` version

| Aspect | `losses.py` (production) | `utils.py` (prototype v4) |
|--------|--------------------------|---------------------------|
| `num_updates` counter | Not present | Present (line 185) — used for `NBATCH_PSEUDO_WARMUP` |
| `class_freq` attribute | Not exposed (counts returned from `update()` only) | Separate `class_freq` tensor stored on the object (lines 228-229) — accessed directly as `label_tracker.class_freq` |
| `class_weights` sync | Updated in-place | Copied from `class_freq` via `.copy_()` |
| Dead class handling | `store[store < 1.0/total] = 0.0` | `store[store < 1e-5] = 0.0` (line 208) |
| `get_class_weights()` when empty | Returns `None` | Returns `torch.ones_like(store)` (line 250) |
| `share_memory_()` | Not used | Commented out (lines 182, 184) |

**Action**: Merge the following from the prototype into `losses.py`'s `LabeledRateTracker`:
- Add `num_updates` counter — incremented on each `update()` call, needed for `NBATCH_PSEUDO_WARMUP` guard (`start_v4_sqlite.py:386`: `label_tracker.num_updates > NBATCH_PSEUDO_WARMUP`)
- Add `class_freq` as a stored tensor attribute — the training loop accesses it directly via `sum(label_tracker.class_freq) > 0` (`start_v4_sqlite.py:386`)

**Note**: `AdaptiveThreshold` in the prototype is already set to CUDA device (not CPU). No device change needed for that class.

**Scoping note**: Production `training.py` already passes only the un-repeated `[B]` sequential-batch labels to `label_tracker.update()` (`raw_labels.to(device)` at `training.py:457`, not the `[V*B]` `labels` tensor) — this matches the desired `labels[0:nbase_ids]` behavior. Once the enriched dataloader (§3.2) is introduced, `raw_labels` must remain scoped to the sequential-only batch, explicitly excluding enriched/candidate-pool patches, to preserve this property.

### 5.2 `AdaptiveThreshold` — add to losses module

**Action**: Add `AdaptiveThreshold` class from `ps_prototypes_v2/utils.py:1396` to `losses.py`.

**Purpose**: Per-class adaptive confidence thresholds for pseudo-label selection, replacing the fixed `PSEUDO_THRESH` threshold. Placing it in `losses.py` avoids an inverted import dependency (`losses.py` would otherwise need to import from `scoring.py` to implement `prediction_loss_pseudo_sce_adaptive`).

---

## 6. Critical Bug Fix: Labels from Different Views

### 6.1 The issue

The line:
```python
labels = labels.repeat(len(views))
```
at `start_v4_sqlite.py:362` repeats ground truth labels across all views. Combined with:
```python
proj_emb = proj_emb.view(-1, proj_emb.shape[-1])
proj_coords = proj_coords.view(-1, 2)
pred_logits = pred_logits.view(-1, pred_logits.shape[-1])
```

The flat layout after `view(-1)` is `[V*B, ...]` in **views-major** order: `[v0_b0, v0_b1, ..., v1_b0, v1_b1, ...]`.

The `labels.repeat(V)` produces `[l_b0, l_b1, ..., l_bN, l_b0, l_b1, ...]` matching this views-major layout.

### 6.2 What was broken in v3

In `start_v3.py:274`, `torch.stack(views_gpu, dim=1)` produces `[B, V, C, H, W]` which when flattened with `flatten(0, 1)` becomes `[B*V, ...]` in **samples-major** order: `[b0_v0, b0_v1, ..., b1_v0, b1_v1, ...]`.

This means `labels.repeat(V)` does NOT align with the flat tensor layout — labels for patch 0 appear at indices `0, V, 2V, ...` but the flat tensor has them at `0, 1, ...` for the first view.

### 6.3 Fix in v4

`torch.stack(views_gpu, dim=0)` produces `[V, B, C, H, W]` which when flattened with `flatten(0, 1)` becomes `[V*B, ...]` in **views-major** order, correctly aligned with `labels.repeat(V)`.

**Status**: This fix is already present in the production `losses.py` — `prediction_loss_pseudo` already assumes views-major layout `[v0_b0, v0_b1, ...]`. The integration task is to ensure the training loop in `training.py` uses `torch.stack(views_gpu, dim=0)` (not `dim=1`) when constructing the view tensor, so the layout assumption in `losses.py` remains satisfied.

---

## 7. Integration Checklist

**Note**: Line numbers cited below reflect the state of the codebase as of this
update. Commit `a3c1f6bdaac7db18d596d9454cdb8fc17cfb7926` (merged DL
actor/freeze-control feature) already shifted several line numbers from the
original plan draft — re-verify exact locations against HEAD before editing.

### 7.1 Database changes
- [ ] Add `train_priority` column to `patch_model()` in `patchsorter/db/head_client/models.py`
- [ ] Add partial index on `train_priority` where `train_priority > 0` (SQL migration)

### 7.2 New classes to add to `patchsorter/dl/`
- [ ] `IterableShardDataset(torch.utils.data.IterableDataset)` — sequential shard iterator; subsumes DB fetch, image decode, and NVIEWS augmentation inside `__iter__` (place in `datasets.py`, replaces `ShardDataset`)
- [ ] `EnrichedInfiniteIterableDataset(torch.utils.data.IterableDataset)` — enriched infinite dataloader (place in `datasets.py`, from `CandidatePoolIterableDataset`)
- [ ] `CandidatePool` — in-memory candidate pool with score decay + `has_labels()` method (place in `datasets.py`, from `GTCandidatePool`)
- [ ] `AdaptiveThreshold` — per-class adaptive threshold (place in `losses.py`, from `utils.py:1396`)
- [ ] `ScoreWriter` — DB score writer using batched updates (place in `scoring.py`; calls the DB worker client but belongs in the DL layer, not the DB layer)
- [ ] `SessionManager.dispose_engine()` — new helper in `patchsorter/db/utils.py` wrapping `self.engine.dispose()`, called from each `DataLoader` worker's `worker_init_fn` for spawn-safety (§3.1)

### 7.3 Loss functions to add/update in `losses.py`
- [ ] Rename `simclr_loss()` to `swav_loss()` and replace its NT-Xent implementation with the SwAV prototype-assignment computation from `ps_prototypes_v2/utils.py:1191`
- [ ] Add `AdaptiveThreshold` class (from `utils.py:1396`)
- [ ] Add `prediction_loss_pseudo_sce_adaptive()` (from `utils.py:1331`)
- [ ] Add `rank_uniform_loss()`
- [ ] Remove `max_mean_discrepancy()` call and `MAX_MEAN_LOSS` weight constant from `training.py` (function may remain in `losses.py` as dead code for now)
- [ ] Add `compute_weighting_scores()` to `patchsorter/dl/scoring.py`

### 7.4 `LabeledRateTracker` updates in `losses.py`
- [ ] Add `num_updates` counter (incremented each `update()` call)
- [ ] Add `class_freq` as a stored tensor attribute (required by training loop guard `sum(label_tracker.class_freq) > 0`)
- [ ] Update `get_class_weights()` to return uniform weights when empty (not None)
- [ ] Update dead class threshold from `1.0/total` to `1e-5`

### 7.5 Training loop changes in `training.py`
- [ ] Replace plain-iterable `ShardDataset` with `IterableShardDataset` + `DataLoader` (`batch_size=None`, `num_workers=N`, `multiprocessing_context="spawn"`, `worker_init_fn` calling `dispose_engine()` + RNG reseed) — see §3.1
- [ ] Restructure `train_worker()` to support dual dataloader pattern
- [ ] Add `dataloader_sequential` iteration (until exhaustion)
- [ ] Add `dataloader_enriched` iteration (within sequential loop)
- [ ] Enriched loop calls `wait_for_unfreeze(actor)` / checks `actor.get_termination_signal.remote()` at the same `POLL_FROZEN_EVERY_N_BATCHES` cadence as the sequential loop (`training.py:342-353`)
- [ ] GPU-side batch concatenation (preserving v4 pattern)
- [ ] Handle `None` enrichment batches when labels not yet found (sequential-only training)
- [ ] Only sequential predictions saved
- [ ] Only base (sequential) batch labels update tracker — use `labels[0:nbase_ids]` (production: keep `raw_labels` scoped to the sequential-only batch, see §5.1)
- [ ] `train_priority` score update per batch on sequential part only — pass `nbase_ids` (not `len(ids)`) to `compute_weighting_scores()`
- [ ] Update loss computation to match prototype structure exactly: SwAV on embeddings only (remove `simclr_coord_loss` term), separate `PRED_SUP_LAMBDA`/`PRED_PSEUDO_LAMBDA` weights, split `SEMANTIC_LAMBDA`, drop MMD term
- [ ] Adaptive threshold for pseudo-labels (use `AdaptiveThreshold` instance; guard with `label_tracker.num_updates > NBATCH_PSEUDO_WARMUP`)
- [ ] Normalize `joint_head.prototypes.data` after each optimizer step

### 7.6 Config migration
- [ ] Apply all constant renames, splits, and value changes per the table in §4.4
- [ ] Split `SEMANTIC_LAMBDA` into `SEMANTIC_COORD_LAMBDA = 1.0` and `SEMANTIC_EMB_LAMBDA = 10.0`
- [ ] Rename `SIMCLR_EMB_LOSS` → `SWAV_EMB_LOSS`
- [ ] Rename `PRED_LAMBDA` → `PRED_SUP_LAMBDA` and update value from `100.0` to `10_000.0`
- [ ] Replace `PSEUDO_PRED_LAMBDA = 0.4` with `PSEUDO_PRED_LAMBDA = 0.0001` and add derived `PRED_PSEUDO_LAMBDA = PRED_SUP_LAMBDA * PSEUDO_PRED_LAMBDA`
- [ ] Set `COORD_CONTRASTIVE_LOSS = 0` (currently `1.0` and active in production)
- [ ] Remove `MAX_MEAN_LOSS`
- [ ] Add `RANK_UNIFORM_LOSS = 10_000.0`
- [ ] Add SwAV hyperparameters: `SWAV_PROTOTYPES=300`, `SWAV_KMEANS_ITERS=10`, `SWAV_SINKHORN_ITERS=3`, `SWAV_EPS=0.05`
- [ ] Add `NBATCH_PSEUDO_WARMUP` constant
- [ ] Add `GT_*` constants for candidate pool sizing
- [ ] Add `K_NEIGHBORS`, `GT_SPATIAL_RARITY_ALPHA`, `GT_CLASS_RARITY_ALPHA`
- [ ] Add `GT_LABEL_CHECK_INTERVAL` constant (default 10 batches)

### 7.7 Label class unassigned ID change (§2.4)
- [ ] Update `UNASSIGNED_CLASS_ID` constant from `1` to `-1` in `config/constants.py`
- [ ] Update seeding SQL in `database_manager.py` to use `label_class_id = -1`
- [ ] Remove `autoincrement=True` from `LabelClass.label_class_id` column in `models.py`
- [ ] Add `setval()` call to initialize sequence at 0 after `create_all()`
- [ ] Audit all `label_class_id == 1` references and update to use `UNASSIGNED_CLASS_ID` or `-1`
- [ ] Update docstrings referencing `label_class_id = 1` or `1 (unassigned)`
- [ ] Update `image.py:165` to use `UNASSIGNED_CLASS_ID` instead of literal `1`

### 7.8 Augmentation integration
- [ ] Verify `augmentations.py` is compatible with prototype's `get_transforms()`

---

## 8. Open Questions — Resolved

1. **Priority column vs score_timestamp**: ✅ `train_priority` replaces `score_timestamp`.
2. **Partial index scope**: ✅ Partial indexes on both `train_priority` (§2.1) and `label_class_id > 0` (§2.2).
3. **Backend for enriched dataloader**: ✅ Production uses PostgreSQL via worker client (not SQLite). SQLite is prototyping-only.
4. **SwAV prototypes source**: ✅ Add `prototypes` attribute to `JointHead` model. Copy `swav_loss()` from prototype as-is; keep `SWAV_KMEANS_ITERS` as variable.
5. **`compute_weighting_scores` integration**: ✅ Computed per-batch on the sequential part of the batch.
6. **AdaptiveThreshold device**: ✅ Already set to CUDA in prototype. No change needed.
7. **ScoreWriter for PostgreSQL**: ✅ Place in `patchsorter/dl/scoring.py` using batched updates (not COPY). Belongs in the DL layer (calls the DB worker client); placing it in the DB layer would mix ML training concerns into the data access layer.
8. **`COORD_CONTRASTIVE_LOSS`**: ✅ Set to 0. Matching prototype loss computation is the priority.
9. **`SIMCLR_EMB_LOSS` rename**: ✅ Rename to `SWAV_EMB_LOSS`.
10. **`PRED_SUP_LAMBDA` weight**: ✅ Confirmed at 10,000.
11. **`train_priority` column migration**: ✅ In this development instance, the database will be recreated after the SQLAlchemy schema is updated. No ALTER TABLE migration needed.
12. **Enriched dataloader sharding**: ✅ Query across shards via manual UNION on PostgreSQL (not Citus), with `ORDER BY train_priority` + `LIMIT`.
13. **Loss weight constants**: ✅ All constants from `configs.py` are preserved as-is — they have been tuned in the prototype.
14. **New constants (`NBATCH_PSEUDO_WARMUP`, `GT_*`, `K_NEIGHBORS`)**: ✅ Values preserved from prototype — carefully tuned and should not be modified.
15. The tmp_label column included in the prototype was used for simulating a user iteratively adding labels and should not be ported into production.
16. **Label-waiting before enrichment**: ✅ `CandidatePool.has_labels()` checks DB periodically (every N batches) for `label_class_id > 0`. Until labels exist, enriched dataloader yields `None` and training runs sequential-only. Once labels found, pool loads and enrichment begins normally.
17. **Unassigned class ID**: ✅ Changed from `1` to `-1`. Sequence starts at 0 so user classes get IDs 0, 1, 2, ... Partial index uses `WHERE label_class_id > 0`. Existing production DBs need a migration script; development instance is unaffected.
18. **`priority` naming collision**: ✅ Renamed to `train_priority` to avoid clashing with the existing prediction-source `priority` field returned by `PatchStore._paginated_pred_join()` (`patch.py`) and exposed via the API.
19. **Dataloader implementation pattern**: ✅ Both `IterableShardDataset` and `EnrichedInfiniteIterableDataset` are genuine `torch.utils.data.IterableDataset` subclasses wrapped in `DataLoader` — not plain-iterable consumption like the current `ShardDataset`. See §3.
20. **Cross-process DB session safety**: ✅ `DataLoader(multiprocessing_context="spawn", worker_init_fn=...)`; `worker_init_fn` calls a new `SessionManager.dispose_engine()` and reseeds NumPy/Python RNGs per worker.

---

## 9. File Structure After Integration

```
patchsorter/dl/
├── __init__.py
├── augmentations.py          # existing
├── losses.py                 # updated: swav_loss (replaces simclr_loss), AdaptiveThreshold, adaptive pseudo, rank_uniform, tracker
├── model.py                  # updated: JointHead.prototypes added
├── training.py               # updated: dual dataloader loop (IterableDataset + DataLoader), constants updated to match prototype, MMD/coord-contrastive removed
├── datasets.py               # NEW: IterableShardDataset, EnrichedInfiniteIterableDataset, CandidatePool
└── scoring.py                # NEW: compute_weighting_scores, ScoreWriter
```

`patchsorter/db/utils.py` also requires a small update outside this directory: add `SessionManager.dispose_engine()` (§3.1), used by the new `DataLoader` `worker_init_fn`s for spawn-safe DB connections.
