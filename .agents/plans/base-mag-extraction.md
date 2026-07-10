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

Same extraction logic in the CSV validation function (around line 167-201). For each row, if the image path exists, open it with `large_image` and extract `magnification`. Add `base_mag` to each row dict.

### 4. Backend — `process_row` (graceful fallback when base_mag is null)
**File:** `patchsorter/api/v1/upload/actor.py`

Update the `process_row` function (line 245-251):
```python
# Determine base_mag
if process_row_arg.base_mag is not None:
    base_mag = process_row_arg.base_mag
else:
    base_mag = ts.getMetadata().get("magnification")
    if base_mag is None:
        # Final fallback: raise with a clear message
        raise ValueError(
            f"base_mag not provided and could not be extracted from image metadata "
            f"for {image_path}"
        )
```

This is the same logic as now, just making the intent explicit: accept from request first, extract from image as fallback.

### 5. Frontend — add `MAGNIFICATION_OPTIONS` constant
**File:** `patchsorter/client/src/constants.ts`

```typescript
export const MAGNIFICATION_OPTIONS: number[] = [2, 4, 5, 10, 20, 40, 100]
```

(Use the actual magnification values relevant to your scanners. Adjust the list as needed.)

### 6. Frontend — `ReviewRow` type (add `base_mag`)
**File:** `patchsorter/client/src/components/projectPage/useUpload.ts`

Add a local interface augmentation:
```typescript
export interface ReviewRowWithMag {
    image: string
    mask: string
    csv: string
    status: string
    error: string
    base_mag: number | null
}
```

### 7. Frontend — `StepReview` (editable base_mag column)
**File:** `patchsorter/client/src/components/projectPage/StepReview.tsx`

**Changes:**
- Add `base_mag` to the `buildColumns()` return array, between `status` and `error`:
  ```typescript
  {
      id: 'base_mag',
      name: 'Base Mag',
      field: 'base_mag',
      formatter: (_row: number, _cell: number, value: unknown) => {
          const v = Number(value ?? '')
          return v ? String(v) : '<span class="text-muted">—</span>'
      },
  },
  ```

- Make the column editable using a Slickgrid `Editor`. The column definition needs:
  ```typescript
  {
      id: 'base_mag',
      name: 'Base Mag',
      field: 'base_mag',
      editor: true,
      formatter: ...,
  }
  ```

- For a dropdown with specific options, create a custom formatter/editor pair. The simplest approach: use a `<select>` in the cell via a `formatter` that returns HTML, and handle `onCellChange` via `gridOptions` to capture edits.

- Update the `dataset` memo to include `base_mag`:
  ```typescript
  const dataset = useMemo(() =>
      (reviewData ?? []).map((row, i) => ({
          id: i,
          image: row.image,
          mask: row.mask,
          csv: row.csv,
          error: row.error,
          status: row.status,
          base_mag: row.base_mag,
      })),
      [reviewData],
  )
  ```

### 8. Frontend — `UploadWizardModal` (propagate base_mag to process)
**File:** `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx`

Update `handleProcess` (line 234-237):
```typescript
body: {
    paths: okRows.map(r => ({
        image: r.image,
        mask: r.mask,
        csv: r.csv,
        base_mag: r.base_mag || null,
    })),
},
```

### 9. Regenerate TypeScript client
**Command:** Run from `patchsorter/client/`:
```bash
npm run openapi-ts
```

This regenerates `types.gen.ts` and `sdk.gen.ts` from the backend's OpenAPI spec (which now includes `base_mag` on `ReviewRow`).

---

## Execution order

1. **`models.py`** — Add `base_mag` to `ReviewRow`
2. **`actor.py`** — Update `_validate_mixed` and `_validate_image_csv` to extract and include `base_mag`; update `process_row` to accept null + re-extract
3. **`constants.ts`** — Add `MAGNIFICATION_OPTIONS`
4. **`useUpload.ts`** — Add local `ReviewRowWithMag` interface
5. **`StepReview.tsx`** — Add base_mag column + dropdown editor; update dataset mapping
6. **`UploadWizardModal.tsx`** — Propagate `base_mag` in process request body
7. **Regenerate client** — `npm run openapi-ts`
8. **Fix types** — Update any remaining TypeScript references to use the regenerated type

---

## Notes

- The `ProcessRow` type already has `base_mag?: number | null` in the generated client, so no backend model changes needed there.
- The `objectRef.hex` bug from the earlier crash is a separate one-line fix (`ref.hex` → `ref.hex()` call). Consider fixing that in the same PR.
- For the Slickgrid dropdown editor, `slickgrid-react` supports custom editors. The simplest pattern is a formatter that renders `<select>` HTML and a cell change handler that updates the dataset.
