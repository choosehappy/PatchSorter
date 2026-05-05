# Trigger Function Code Review

Critical review of `update_cm_shard` (INSERT trigger) and `update_cm_on_patch_update` (UPDATE trigger) in `db_client.py`.

---

## Bugs

### Bug 1 (High): UPDATE trigger doesn't cover `pred_patch_last` — breaks the INSERT trigger's `neg` CTE

Trace the lifecycle:

1. **Epoch N**: INSERT trigger fires, CM records `(pred_label_N, gt_label_X)` for a patch.
2. **User changes gt_label X → Y**: UPDATE trigger fires, joins `pred_patch_latest` (which still has the prediction), correctly updates CM to `(pred_label_N, gt_label_Y)`. ✓
3. **`rotate_tables()`**: `pred_patch_latest` → `pred_patch_last`. New `pred_patch_latest` is empty.
4. **User changes gt_label Y → Z** (inter-epoch): UPDATE trigger fires, joins **empty** `pred_patch_latest` → **no CM update**. CM still shows `(pred_label_N, gt_label_Y)`. ✗
5. **Epoch N+1 INSERT trigger fires** for that patch: `neg` CTE joins `pred_patch_last` × **current** `patch.label_class_id` (Z) → decrements `(pred_label_N, gt_label_Z)`. But CM has `(pred_label_N, gt_label_Y)`, not Z. **Result: `(pred_label_N, gt_label_Z)` goes to −1; `(pred_label_N, gt_label_Y)` stays at 1. Both are wrong.**

**Fix:** the UPDATE trigger must also resolve the `pred_patch_last` shard (using the same `to_regclass()` guard pattern from the INSERT trigger) and join against it when `pred_patch_latest` is empty for a given `patch_id`.

---

### Bug 2 (Medium): `DELETE WHERE count = 0` should be `DELETE WHERE count <= 0` — in both triggers

```sql
EXECUTE format('DELETE FROM %s WHERE count = 0', TG_ARGV[0]);
```

Bug 1 can produce negative counts. A concurrent race (two workers writing overlapping delta batches before either reads the current count) can also produce a transient negative. `= 0` misses both cases.

---

### Bug 3 (Medium): Consequence of Bug 1 — INSERT trigger `neg` CTE will decrement the wrong CM cells

The `neg` CTE uses `patch.label_class_id` (current gt_label) as the key to decrement. This is only correct if the CM was kept up-to-date for `pred_patch_last` predictions when gt_labels changed inter-epoch. Without the Bug 1 fix, `neg` routinely decrements a cell that was never incremented.

---

## Weaknesses

### Weakness 4: `v_pred_last_shard IS NULL` conflates two distinct conditions

```sql
IF v_pred_last_shard IS NULL THEN
```

This is NULL for two distinct reasons:

- `pred_patch_last` table doesn't exist → `to_regclass()` returns NULL → `WHERE logicalrelid = NULL` matches nothing → `SELECT INTO` gets no row. **Expected on first epoch.**
- `pred_patch_last` table exists but has no matching shard row. **Citus catalog inconsistency — silent wrong results.**

Recommended guard:

```sql
IF to_regclass(TG_TABLE_SCHEMA || '.pred_patch_last') IS NULL THEN
    -- first epoch, simple increment path
ELSIF v_pred_last_shard IS NULL THEN
    RAISE EXCEPTION 'could not resolve pred_patch_last shard for shardid %', v_pred_shardid;
ELSE
    -- delta path
END IF;
```

---

### Weakness 5: `bucket_date` semantics are ambiguous

`bucket_date` is not part of the primary key — `(grid_cell_i, grid_cell_j, pred_label, gt_label, shard_id)`. Every `ON CONFLICT` only updates `count`; `bucket_date` is never changed after the row is created. So it records "date this cell was first created," not a time-bucket. The column name implies the latter. If per-day CM snapshots are ever needed, this is the wrong schema.

---

### Minor: `shard_id` is always hardcoded to `0`

Both triggers always insert `shard_id = 0`. CM rows are already physically partitioned by Citus co-location. The column adds nothing to current routing. It is in the PK, so it enforces a unique constraint per cell — but if it was ever intended as a real partition key or epoch identifier, the current design doesn't use it that way.

---

## Summary

| # | Severity | Where | Status | Issue |
|---|----------|-------|--------|-------|
| 1 | **High** | UPDATE trigger | **Fixed** | Doesn't join `pred_patch_last`; inter-epoch gt_label changes are silently dropped, making INSERT trigger's `neg` CTE decrement the wrong CM cells |
| 2 | **Medium** | Both triggers | **Fixed** | `DELETE WHERE count = 0` changed to `<= 0` |
| 3 | **Medium** | INSERT trigger | **Fixed** (via #1) | Consequence of #1: `neg` CTE produces phantom negative counts until #1 is fixed |
| 4 | Medium | Both triggers | **Fixed** | `v_pred_last_shard IS NULL` conflated "first epoch" with "catalog corruption"; explicit `RAISE EXCEPTION` guard added |
| 5 | Low | Schema / both | **Fixed** | `bucket_date` now updated to `CURRENT_DATE` on every `ON CONFLICT DO UPDATE` — reflects last-modified date |
| 6 | Low | Both | Won't fix | `shard_id = 0` hardcoded; required as distribution column by Citus; triggers write directly to physical shard tables so value doesn't affect routing |

---

## Correctness Confirmations

Things that are correct:

- **`format()` arg counts**: all three `EXECUTE format(...)` calls have the correct number of `%s` tokens matched to arguments. ✓
- **`%s` vs `%I` for schema-qualified names**: correctly uses `%s` so the dot is treated as a schema separator. ✓
- **Statement-level triggers with transition tables**: `FOR EACH STATEMENT … REFERENCING NEW TABLE AS new_rows` fires once per batch — efficient and correct. ✓
- **`neg` CTE using current gt_label**: logically correct *provided* Bug 1 is fixed, because the CM reflects current gt_label values for all active prediction rows. ✓
- **Brand-new patches (no row in `pred_patch_last`) in the delta `ELSE` path**: the `neg` inner join naturally excludes them; they contribute only to `pos`. Net delta = +1. ✓
- **No-change predictions (same pred/gt/cell across epochs)**: `neg` = −1, `pos` = +1, net = 0, filtered by `HAVING SUM(delta) <> 0`. No unnecessary write. ✓
- **Dollar-quoting nesting** (`$body$` / `$sql$` / `$outer$` / `$cmd$`): all distinct, no collisions. ✓
