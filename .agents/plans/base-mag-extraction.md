# Plan: base_mag extraction through validation → review → process

## Overview
Add `base_mag` to the validation response, expose it in the review grid as an editable column, and propagate it through the process request. If `base_mag` is null when processing, re-extract from the large_image handle instead of raising.

---

## Changes

### 1. Backend — `ReviewRow` model (add `base_mag`)
**File:** `patchsorter/api/v1/upload/models.py`

Add `base_mag: float | None = None` to `ReviewRow`:
```python
class ReviewRow(BaseModel):
    image: str
    mask: str
    csv: str
    status: str
    error: str
    base_mag: float | None = None
```

### 2. Backend — `_validate_mixed` (extract base_mag during validation)
**File:** `patchsorter/api/v1/upload/actor.py`

In the row-building loop (after line 140), for each valid image path, open the tile source and extract magnification:

```python
# large_image is already imported at top of file
```

In the loop where rows are built (around line 137-162):
```python
base_mag: float | None = None
try:
    ts = large_image.open(str(img_path))
    base_mag = ts.getMetadata().get("magnification")
except Exception:
    base_mag = None
```

Add `base_mag` to each row dict:
```python
rows.append(dict(
    image=img_rel,
    mask=mask_rel,
    csv=csv_rel,
    status="ok" / "error",
    error=...,
    base_mag=base_mag,
))
```

### 3. Backend — `_validate_image_csv` (same treatment)
**File:** `patchsorter/api/v1/upload/actor.py`

Same extraction logic in the CSV validation function. Paths in the CSV manifest are relative to `MOUNTS_PATH` (per the `FileStore` convention). Resolve each path to an absolute path using `os.path.join(constants.MOUNTS_PATH, img)` before passing to `large_image.open`. Only attempt to open the image when the resolved path exists (i.e. the row has no errors). Add `base_mag` to each row dict.

### 4. Backend — `process_row` (improve error message)
**File:** `patchsorter/api/v1/upload/actor.py`

The fallback logic is already implemented. The only change is to include the `image_path` in the `ValueError` message so failures are easier to diagnose:
```python
if base_mag is None:
    raise ValueError(
        f"base_mag not provided and could not be extracted from image metadata "
        f"for {image_path}"
    )
```

### 5. Frontend — add `MAGNIFICATION_OPTIONS` constant
**File:** `patchsorter/client/src/constants.ts`

```typescript
export const MAGNIFICATION_OPTIONS: number[] = [2, 4, 5, 10, 20, 40, 100]
```

(Use the actual magnification values relevant to your scanners. Adjust the list as needed.)

### 6. Frontend — regenerate TypeScript client
**Command:** Run from `patchsorter/client/`:
```bash
npm run openapi-ts
```

This regenerates `types.gen.ts` and `sdk.gen.ts` from the backend OpenAPI spec. After this step `ReviewRow` in the generated client will include `base_mag: number | null`. No separate interface is needed — `useUpload.ts` already re-exports `ReviewRow` from `../../api_client`, so all consumers receive the updated type automatically.

### 7. Frontend — `StepReview` (editable base_mag column)
**File:** `patchsorter/client/src/components/projectPage/StepReview.tsx`

**Props change** — add an `onRowChange` callback so cell edits propagate to the parent:
```typescript
interface StepReviewProps {
    approach: Approach | null
    reviewData: ReviewRow[] | null
    isLoading: boolean
    onRowChange: (index: number, updates: Partial<ReviewRow>) => void
}
```

**`buildColumns` change** — add a `base_mag` column between `csv` and `error`, using SlickGrid's `SelectEditor` with `MAGNIFICATION_OPTIONS` as its collection:
```typescript
import { Editors } from 'slickgrid-react'
import { MAGNIFICATION_OPTIONS } from '../../constants'

// inside buildColumns():
{
    id: 'base_mag',
    name: 'Base Mag',
    field: 'base_mag',
    sortable: true,
    editor: Editors.SingleSelect,
    editorOptions: {
        collection: [
            { value: null, label: '—' },
            ...MAGNIFICATION_OPTIONS.map(m => ({ value: m, label: String(m) })),
        ],
    },
    formatter: (_row: number, _cell: number, value: unknown) => {
        const v = Number(value ?? 0)
        return v ? String(v) : '<span class="text-muted">—</span>'
    },
},
```

**`gridOptions` change** — enable cell editing and wire `onCellChange` to call `onRowChange`:
```typescript
const gridOptions: GridOption = {
    ...,
    editable: true,
    autoEdit: false,
}
```

Bind the cell-change event on the SlickgridReact component:
```typescript
<SlickgridReact
    ...
    onCellChange={e => {
        const { row, cell: _cell, dataContext } = e.detail.args
        onRowChange(row, { base_mag: dataContext.base_mag ?? null })
    }}
/>
```

**`dataset` memo** — include `base_mag`:
```typescript
const dataset = useMemo(() =>
    (reviewData ?? []).map((row, i) => ({
        id: i,
        image: row.image,
        mask: row.mask,
        csv: row.csv,
        error: row.error,
        status: row.status,
        base_mag: row.base_mag ?? null,
    })),
    [reviewData],
)
```

### 8. Frontend — `UploadWizardModal` (onRowChange + propagate base_mag to process)
**File:** `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx`

**Add `onRowChange` handler** that updates `reviewData` state so edits made in `StepReview` are reflected when processing:
```typescript
const handleRowChange = useCallback(
    (index: number, updates: Partial<ReviewRow>) => {
        setReviewData(prev =>
            prev ? prev.map((row, i) => (i === index ? { ...row, ...updates } : row)) : prev
        )
    },
    [],
)
```

**Pass `onRowChange` to `StepReview`:**
```typescript
<StepReview
    approach={approach}
    reviewData={reviewData}
    isLoading={isReviewLoading}
    onRowChange={handleRowChange}
/>
```

**Update `handleProcess`** to include `base_mag`, using `??` (not `||`) to preserve `0` as a valid sentinel:
```typescript
body: {
    paths: okRows.map(r => ({
        image: r.image,
        mask: r.mask,
        csv: r.csv,
        base_mag: r.base_mag ?? null,
    })),
},
```

### 9. (No separate step — regeneration is step 6 above)

---

## Execution order

1. **`models.py`** — Add `base_mag` to `ReviewRow`
2. **`actor.py`** — Update `_validate_mixed` and `_validate_image_csv` to extract and include `base_mag`; update `process_row` error message
3. **Regenerate client** — `npm run openapi-ts` (so `ReviewRow` has `base_mag` before touching frontend)
4. **`constants.ts`** — Add `MAGNIFICATION_OPTIONS`
5. **`StepReview.tsx`** — Add `onRowChange` prop; add base_mag `SelectEditor` column; update dataset mapping
6. **`UploadWizardModal.tsx`** — Add `handleRowChange`; pass `onRowChange` to `StepReview`; propagate `base_mag` in process request body

---

## Notes

- The `ProcessRow` type already has `base_mag?: number | null` in the generated client, so no backend model changes needed there.
- The `objectRef.hex` bug from the earlier crash is a separate one-line fix (`ref.hex` → `ref.hex()` call). Consider fixing that in the same PR.
- `MAGNIFICATION_OPTIONS` is passed to `SelectEditor` via `editorOptions.collection`; each entry must be `{ value, label }`. A leading `{ value: null, label: '—' }` entry lets the user clear the field.
- In `_validate_mixed`, only attempt `large_image.open` for rows with a non-empty `img_rel` (i.e. skip the early-exit error row where `image=""`). Wrap the open call in `try/except` and default `base_mag` to `None` on failure.
- In `_validate_image_csv`, resolve the relative path to absolute using `os.path.join(constants.MOUNTS_PATH, img)` before calling `large_image.open` — consistent with how the `FileStore` convention handles all paths.
