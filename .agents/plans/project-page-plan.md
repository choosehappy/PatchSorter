# Project Page Implementation Plan

## Overview
Build the full Project Page with three sections (Metadata, Label Classes, Images) using `slickgrid-universal` for table rendering, plus all required backend endpoints.

---

## Phase 1: Backend — Database Schema Changes

### 1.1 Add `creation_ts` column to `project` table
- Add `creation_ts TIMESTAMP NOT NULL DEFAULT NOW()`
- Update `ProjectStore.create()` to explicitly set `creation_ts`

---

## Phase 2: Backend — New Endpoints

### 2.1 `GET /api/v1/projects/{project_id}/stats/` — Project-level statistics
- `num_images` from `image` table
- `patch_size` from `settings` table (key `patch_size`)
- `num_label_classes` from `label_class` table (plain count)
- `total_objects` from `project{N}_patch`
- `labeled_count` from `project{N}_patch` where `label_class_id > 1`
- `creation_date` = `project.creation_ts`
- `modification_date` = `MAX(bucket_date)` from coarsest confusion matrix table (`l8`)

### 2.2 `GET /api/v1/projects/{project_id}/settings/` — All settings
- Returns raw settings as list of `{setting_key, setting_value, setting_type, default_value, disabled}` from `SettingsStore.get_all_within_project_scope()`

### 2.3 `GET /api/v1/projects/{project_id}/images/` — List images
- Returns `image_id`, `name`, `base_width`, `base_height`, `upload_ts` for each image
- Uses `ImageStore.list_by_project()`

### 2.4 `GET /api/v1/projects/{project_id}/images/{image_id}/stats/` — Per-image stats
- `total_objects`, `unlabeled_count`, per-class counts as `{label_class_id: count}`
- Queries `project{N}_patch` with `GROUP BY label_class_id`

### 2.5 `GET /api/v1/projects/{project_id}/images/{image_id}/thumbnail/` — Thumbnail
- Opens WSI via `large_image`, extracts 256x256 thumbnail
- Returns as JPEG with `Cache-Control: public, max-age=3600`
- In-memory LRU cache (e.g., `functools.lru_cache(maxsize=128)`) on the tile source result

### 2.6 `GET /api/v1/projects/{project_id}/images/export?image_ids=1,2,3` — Multi-image export
- Exports labels for specified images as JSON
- Returns downloadable file

### 2.7 `GET /api/v1/projects/{id}/images/export` — Project-wide export
- Query param `image_ids` (comma-separated, or omit for all)
- Returns JSON with all labels for the selected images

---

## Phase 3: TypeScript Client Regeneration

- Regenerate with `@hey-api/openapi-ts`
- New types: `ProjectStatsResponse`, `SettingsResponse`, `ImageResponse`, `ImageSummaryResponse`
- New SDK functions for all new endpoints

---

## Phase 4: Frontend — Project Page

### 4.1 Dependencies
```json
"dependencies": {
  "slickgrid-universal": "^*",
  "slickgrid-react": "^*",
  "react-bootstrap": "^2.10.10"
}
```

### 4.2 Routing (`main.tsx`)
- Add route: `/project/:projectId/project` → `<ProjectPage />`
- Update `Navigation.tsx` to include breadcrumb link to project page

### 4.3 `ProjectPage` component (`src/routes/projectPage.tsx`)

Uses `react-query` hooks to fetch all data in parallel:
```ts
const { data: project } = useQuery(['project', id], () => getProjectApiV1ProjectsProjectIdGet({ path: { project_id: id } }))
const { data: stats } = useQuery(['projectStats', id], () => getProjectStatsApiV1ProjectsProjectIdStatsGet({ path: { project_id: id } }))
const { data: settings } = useQuery(['projectSettings', id], () => getProjectSettingsApiV1ProjectsProjectIdSettingsGet({ path: { project_id: id } }))
const { data: labelClasses } = useQuery(['labelClasses', id], () => listLabelClassesApiV1ProjectsProjectIdLabelClassesGet({ path: { project_id: id } }))
const { data: images } = useQuery(['projectImages', id], () => listProjectImagesApiV1ProjectsProjectIdImagesGet({ path: { project_id: id } }))
```

### 4.4 Section A: Project Metadata Table — `SlickgridReact` with loading spinners

| Column | Source | Loading State |
|--------|--------|---------------|
| Project Name | `project.project_name` | Spinner |
| Description | `project.description` | Spinner |
| Creation Date | `project.creation_ts` | Spinner |
| Modification Date | `stats.modification_date` | Spinner |
| No. of Images | `stats.num_images` | Spinner |
| Patch Size | `settings.project.patch_size` | Spinner |
| No. of Label Classes | `stats.num_label_classes` | Spinner |
| No. Total Objects | `stats.total_objects` | Spinner |
| No. Labeled | `stats.labeled_count` | Spinner |

Each cell renders a `<CellLoader />` component that shows a Bootstrap spinner while `isLoading` is true, then the formatted value.

### 4.5 Section B: Label Classes Table — `SlickgridReact` with checkbox selection

- **Checkbox column** as leftmost column with header "Select All" checkbox (toggles all rows)
- Columns: `Id`, `Name`, `Color` (custom formatter renders a colored `<span>` swatch), `Created`, Actions (`Edit`, `Delete` buttons)
- **"Delete N label classes"** button below the table (visible when N ≥ 1 rows selected)
- Delete triggers confirmation dialog; on confirm, fires **N parallel DELETE endpoint calls** (one per selected class)
- Selection resets after action completes

### 4.6 Section C: Images Table — `SlickgridReact` with checkbox selection

- **Checkbox column** as leftmost column with header "Select All" checkbox (toggles all rows)
- Base columns: `Thumbnail` (formatter with lazy `<img>` loading + spinner), `Name`, `Width`, `Height`, `Total Objects`, `Unlabeled`, Actions
- **Dynamic per-class columns**: one column per label class, named `No. {name} (GT)`, type `number`, formatter shows spinner while loading then the count
- **Dynamic Actions column**:
  - **0 selected**: per-row "Open Labeler" button → navigates to `/project/:id/labeler?image=:imageId`
  - **N selected (≥ 1)**: replaces per-row actions with "Export annotations from N images" and "Delete N images" buttons
- **"Export annotations from N images" button**: single `GET /images/export?image_ids=...` call — **no-op for now** (just `console.log`)
- **"Delete N images" button**: triggers confirmation dialog; on confirm, fires **N parallel DELETE endpoint calls** (one per selected image)
- Selection resets after action completes

### 4.7 Reusable Selection Component (`TableSelection.tsx`)

```tsx
// Props: items (array), selectedIds (Set), onToggleAll, onToggleOne, onAction (N: number) => void
// Renders:
//   - Table header with "Select All" checkbox
//   - Row checkboxes synced to slickgrid selected rows
//   - Action bar below table: "Delete N {item_type}" button (when N ≥ 1)
// Selection persists while data is loaded; resets when data reloads
```

### 4.8 Loading Indicator Component
```tsx
function CellLoader({ isLoading, value, formatter }: { isLoading: boolean; value?: string|number; formatter?: (v: any) => string }) {
    if (isLoading) return <span className="spinner-border spinner-border-sm" />
    return <span>{formatter ? formatter(value) : value}</span>
}
```

### 4.9 Styling
- Bootstrap classes for layout
- Slickgrid Bootstrap theme CSS
- Responsive: sections stack vertically on narrow screens

---

## Phase 5: Implementation Order

1. **DB schema migrations** — `creation_ts` on project
2. **Backend endpoints** — stats, settings, images, image summary, thumbnail, export, project update
3. **Regenerate TypeScript client**
4. **Install slickgrid dependencies**
5. **Add ProjectPage route + component**
6. **Build TableSelection component** (checkbox selection, select all, action bar)
7. **Build Section A (Metadata)** with CellLoader
8. **Build Section B (Label Classes)** with checkbox selection + delete N
9. **Build Section C (Images)** with checkbox selection, dynamic columns, dynamic Actions column
10. **Wire up Navigation breadcrumb**
11. **Test all flows end-to-end**

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `patchsorter/db/head_client/models.py` | Modify: add `creation_ts` to Project |
| `patchsorter/db/head_client/project.py` | Modify: `create()` sets `creation_ts`; add `update()` method |
| `patchsorter/api/v1/project/routes.py` | Add: `/stats/` and `PUT /{project_id}` endpoints |
| `patchsorter/api/v1/project/models.py` | Add: `ProjectStatsResponse` |
| `patchsorter/api/v1/settings/routes.py` | **Create**: `GET /{project_id}/settings/` |
| `patchsorter/api/v1/settings/models.py` | **Create**: `SettingsResponse` |
| `patchsorter/api/v1/image/routes.py` | **Create**: images list, summary, thumbnail, export endpoints |
| `patchsorter/api/v1/image/models.py` | **Create**: `ImageResponse`, `ImageSummaryResponse` |
| `patchsorter/client/src/routes/projectPage.tsx` | **Create** |
| `patchsorter/client/src/components/TableSelection.tsx` | **Create**: checkbox selection component |
| `patchsorter/client/src/main.tsx` | Modify: add route |
| `patchsorter/client/src/components/Navigation.tsx` | Modify: breadcrumb |
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate |
| `patchsorter/client/package.json` | Modify: add slickgrid deps |
