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

Install via `npm install` in `patchsorter/client/`:
```json
"dependencies": {
  "slickgrid-react": "^9.x",
  "@slickgrid-universal/common": "^9.x"
}
```

CSS theme import (add once at the top of `projectPage.tsx` or in `index.css`):
```ts
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css';
```

> **Note:** `slickgrid-react` re-exports `Column`, `GridOption`, `SlickgridReact`, `SlickgridReactInstance`, `CheckboxSelectColumn`, `RowSelectionModel`, and `Formatters` — import all from `'slickgrid-react'` to avoid version skew.

---

### 4.2 Routing (`main.tsx`)

```tsx
import ProjectPage from './routes/projectPage.tsx'

const router = createBrowserRouter([
    {
        path: '/',
        element: <Root />,
        children: [
            { path: '/project/:projectId/labeler', element: <LabelingPage /> },
            { path: '/project/:projectId/project', element: <ProjectPage /> },
        ],
    },
])
```

---

### 4.3 Navigation breadcrumb (`Navigation.tsx`)

The `Navigation` component already receives `currentProject`. Add a new "Project" breadcrumb link between the project name and "Labeler":

```tsx
{currentProject && (
    <Item>
        <Nav.Link as={Link} to={`/project/${currentProject.id}/project`}>
            Project
        </Nav.Link>
    </Item>
)}
```

`Root` still passes `currentProject = null` (hardcoded TODO). This breadcrumb will appear once that TODO is resolved, but adding the link now is correct.

---

### 4.4 `ProjectPage` component (`src/routes/projectPage.tsx`)

**Top-level structure:**
```tsx
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Container } from 'react-bootstrap'
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css'
import MetadataSection from '../components/projectPage/MetadataSection'
import LabelClassesTable from '../components/projectPage/LabelClassesTable'
import ImagesTable from '../components/projectPage/ImagesTable'
import {
    getProjectApiV1ProjectsProjectIdGet,
    getProjectStatsApiV1ProjectsProjectIdStatsGet,
    getProjectSettingsApiV1ProjectsProjectIdSettingsGet,
    listLabelClassesApiV1ProjectsProjectIdLabelClassesGet,
    listProjectImagesApiV1ProjectsProjectIdImagesGet,
} from '../api_client'

export default function ProjectPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>()
    const projectId = Number(projectIdParam)
    const queryClient = useQueryClient()

    const { data: project, isLoading: projectLoading } = useQuery({
        queryKey: ['project', projectId],
        queryFn: () => getProjectApiV1ProjectsProjectIdGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: stats, isLoading: statsLoading } = useQuery({
        queryKey: ['projectStats', projectId],
        queryFn: () => getProjectStatsApiV1ProjectsProjectIdStatsGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: settings, isLoading: settingsLoading } = useQuery({
        queryKey: ['projectSettings', projectId],
        queryFn: () => getProjectSettingsApiV1ProjectsProjectIdSettingsGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: labelClasses, isLoading: labelClassesLoading } = useQuery({
        queryKey: ['labelClasses', projectId],
        queryFn: () => listLabelClassesApiV1ProjectsProjectIdLabelClassesGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: images, isLoading: imagesLoading } = useQuery({
        queryKey: ['projectImages', projectId],
        queryFn: () => listProjectImagesApiV1ProjectsProjectIdImagesGet({ path: { project_id: projectId } }).then(r => r.data),
    })

    return (
        <Container fluid className="py-3 d-flex flex-column gap-4">
            <MetadataSection
                project={project} projectLoading={projectLoading}
                stats={stats} statsLoading={statsLoading}
                settings={settings} settingsLoading={settingsLoading}
            />
            <LabelClassesTable
                projectId={projectId}
                labelClasses={labelClasses ?? []}
                isLoading={labelClassesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['labelClasses', projectId] })}
            />
            <ImagesTable
                projectId={projectId}
                images={images ?? []}
                labelClasses={labelClasses ?? []}
                isLoading={imagesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['projectImages', projectId] })}
            />
        </Container>
    )
}
```

Sub-components live under `src/components/projectPage/` to keep the route file thin.

---

### 4.5 Section A: Metadata — `MetadataSection.tsx`

A 9-row Bootstrap `<Table>` (not SlickgridReact — a static key-value sheet doesn't benefit from a virtual grid). Each value cell conditionally renders a Bootstrap spinner or the formatted value:

```tsx
const SPINNER = <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />

function Cell({ loading, value }: { loading: boolean; value?: React.ReactNode }) {
    return loading ? SPINNER : <>{value ?? '—'}</>
}

export default function MetadataSection({ project, projectLoading, stats, statsLoading, settings, settingsLoading }) {
    const patchSize = settings?.find(s => s.setting_key === 'patch_size')?.setting_value

    return (
        <section>
            <h5>Project Metadata</h5>
            <Table bordered hover size="sm" style={{ maxWidth: 600 }}>
                <tbody>
                    <tr><td>Project Name</td>      <td><Cell loading={projectLoading}  value={project?.project_name} /></td></tr>
                    <tr><td>Description</td>       <td><Cell loading={projectLoading}  value={project?.description} /></td></tr>
                    <tr><td>Creation Date</td>     <td><Cell loading={projectLoading}  value={project?.creation_ts ? new Date(project.creation_ts).toLocaleString() : undefined} /></td></tr>
                    <tr><td>Modification Date</td> <td><Cell loading={statsLoading}    value={stats?.modification_date ? new Date(stats.modification_date).toLocaleString() : undefined} /></td></tr>
                    <tr><td>No. of Images</td>     <td><Cell loading={statsLoading}    value={stats?.num_images} /></td></tr>
                    <tr><td>Patch Size</td>        <td><Cell loading={settingsLoading} value={patchSize} /></td></tr>
                    <tr><td>No. of Label Classes</td><td><Cell loading={statsLoading}  value={stats?.num_label_classes} /></td></tr>
                    <tr><td>Total Objects</td>     <td><Cell loading={statsLoading}    value={stats?.total_objects} /></td></tr>
                    <tr><td>Labeled</td>           <td><Cell loading={statsLoading}    value={stats?.labeled_count} /></td></tr>
                </tbody>
            </Table>
        </section>
    )
}
```

---

### 4.6 Section B: Label Classes — `LabelClassesTable.tsx`

**Full component skeleton:**
```tsx
import { useRef, useState, useEffect, useCallback } from 'react'
import { Button } from 'react-bootstrap'
import {
    Column, GridOption, SlickgridReact, SlickgridReactInstance,
    CheckboxSelectColumn, RowSelectionModel,
} from 'slickgrid-react'
import ConfirmationModal from '../ConfirmationModal'   // create or reuse
import { deleteLabelClassApiV1ProjectsProjectIdLabelClassesLabelClassIdDelete } from '../../api_client'

export default function LabelClassesTable({ projectId, labelClasses, isLoading, onMutated }) {
    const gridRef = useRef<SlickgridReactInstance | null>(null)
    const checkboxSelector = useRef(new CheckboxSelectColumn({ cssClass: 'slick-cell-checkboxes' }))
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
    const [showDeleteModal, setShowDeleteModal] = useState(false)
```

**Column definitions:**
```tsx
    const colorFormatter = (_row, _cell, value) =>
        `<span style="display:inline-block;width:20px;height:20px;border-radius:3px;background:${value};border:1px solid #ccc"></span> ${value}`

    const actionsFormatter = (_row, _cell, _value, _col, dataContext) => {
        const btn = document.createElement('button')
        btn.className = 'btn btn-danger btn-sm'
        btn.textContent = 'Delete'
        btn.addEventListener('click', (e) => {
            e.stopPropagation()
            // single-row delete: set selectedIds to just this row, show modal
            setSelectedIds(new Set([dataContext.id]))
            setShowDeleteModal(true)
        })
        return btn
    }

    const columns: Column[] = [
        checkboxSelector.current.getColumnDefinition(),
        { id: 'id',      name: 'Id',      field: 'id',         sortable: true },
        { id: 'name',    name: 'Name',    field: 'name',       sortable: true },
        { id: 'color',   name: 'Color',   field: 'color',      sortable: false, formatter: colorFormatter },
        { id: 'created', name: 'Created', field: 'created_ts', sortable: true,
          formatter: (_r, _c, v) => v ? new Date(v).toLocaleDateString() : '' },
        { id: 'actions', name: '',        field: 'id',         sortable: false, formatter: actionsFormatter },
    ]
```

**Grid options:**
```tsx
    const gridOptions: GridOption = {
        enableAutoResize: true,
        enableCheckboxSelector: true,
        enableRowSelection: true,
        rowSelectionOptions: { selectActiveRow: false },
        checkboxSelector: { hideInFilterHeaderRow: false },
        rowHeight: 40,
        forceFitColumns: true,
        autoResize: { container: '#label-classes-container' },
    }
```

**Selection tracking:**
```tsx
    const onGridReady = useCallback((reactGrid: SlickgridReactInstance) => {
        gridRef.current = reactGrid
        reactGrid.slickGrid.onSelectedRowsChanged.subscribe((_e, args) => {
            const ids = new Set(
                args.rows.map(r => (reactGrid.slickGrid.getDataItem(r) as { id: number }).id)
            )
            setSelectedIds(ids)
        })
    }, [])
```

**Dataset:**
```tsx
    const dataset = labelClasses.map(lc => ({
        id: lc.label_class_id,
        name: lc.name,
        color: lc.color,
        created_ts: lc.created_ts,
    }))
```

**Bulk delete handler:**
```tsx
    const handleDelete = async () => {
        await Promise.all(
            [...selectedIds].map(id =>
                deleteLabelClassApiV1ProjectsProjectIdLabelClassesLabelClassIdDelete({
                    path: { project_id: projectId, label_class_id: id }
                })
            )
        )
        setSelectedIds(new Set())
        setShowDeleteModal(false)
        onMutated()
    }
```

**Render:**
```tsx
    return (
        <section>
            <h5>Label Classes</h5>
            <div id="label-classes-container" style={{ height: Math.max(150, labelClasses.length * 40 + 60) }}>
                <SlickgridReact
                    gridId="label-classes-grid"
                    columnDefinitions={columns}
                    gridOptions={gridOptions}
                    dataset={isLoading ? [] : dataset}
                    onReactGridCreated={e => onGridReady(e.detail)}
                />
            </div>
            {selectedIds.size > 0 && (
                <Button variant="danger" size="sm" className="mt-2"
                    onClick={() => setShowDeleteModal(true)}>
                    Delete {selectedIds.size} label class{selectedIds.size > 1 ? 'es' : ''}
                </Button>
            )}
            <ConfirmationModal
                show={showDeleteModal}
                message={`Delete ${selectedIds.size} label class(es)? This cannot be undone.`}
                onConfirm={handleDelete}
                onCancel={() => setShowDeleteModal(false)}
            />
        </section>
    )
}
```

---

### 4.7 Section C: Images Table — `ImagesTable.tsx`

This is the most complex component. It has:
- Per-image stats fetched in parallel (one `useQuery` per image, keyed by `image_id`)
- Columns rebuilt whenever `labelClasses` changes (call `slickGrid.setColumns()`)
- Selection state that swaps the Actions column between per-row and bulk-action modes

**Per-image stats queries:**
```tsx
// Fetch stats for every image in the list; enabled only when images are loaded
const imageStatQueries = useQueries({
    queries: images.map(img => ({
        queryKey: ['imageStats', projectId, img.image_id],
        queryFn: () => getImageStatsApiV1ProjectsProjectIdImagesImageIdStatsGet({
            path: { project_id: projectId, image_id: img.image_id }
        }).then(r => r.data),
        enabled: images.length > 0,
        staleTime: 30_000,
    }))
})
// Build a lookup: image_id → stats (null while loading)
const statsByImageId: Record<number, ImageSummaryResponse | null> = useMemo(() =>
    Object.fromEntries(images.map((img, i) => [
        img.image_id,
        imageStatQueries[i].isSuccess ? imageStatQueries[i].data : null
    ])), [images, imageStatQueries])
```

> `useQueries` is from `@tanstack/react-query` and fires all queries concurrently.

**Column builder (called in `useEffect` and on `labelClasses` change):**
```tsx
const buildColumns = useCallback((selectionSize: number): Column[] => {
    const thumbnailFormatter = (_row, _cell, value) => {
        const src = `/api/v1/projects/${projectId}/images/${value}/thumbnail/`
        return (
            `<span class="spinner-border spinner-border-sm" role="status"></span>` +
            `<span class="text-danger" style="display:none;font-size:1.5rem">&times;</span>` +
            `<img src="${src}" height="56" style="display:none"` +
            ` onload="this.previousElementSibling.previousElementSibling.style.display='none';this.style.display='block'"` +
            ` onerror="this.previousElementSibling.previousElementSibling.style.display='none';this.previousElementSibling.style.display='inline'">`
        )
    }

    const spinnerOrValue = (_row, _cell, value) =>
        value === null
            ? `<span class="spinner-border spinner-border-sm" role="status"></span>`
            : String(value ?? '')

    const actionsFormatter = (_row, _cell, _value, _col, dataContext) => {
        if (selectionSize > 0) return ''   // bulk-action bar replaces per-row actions
        const btn = document.createElement('button')
        btn.className = 'btn btn-primary btn-sm'
        btn.textContent = 'Open Labeler'
        btn.addEventListener('click', (e) => {
            e.stopPropagation()
            navigate(`/project/${projectId}/labeler?image=${dataContext.id}`)
        })
        return btn
    }

    const perClassCols: Column[] = labelClasses.map(lc => ({
        id: `class_gt_${lc.label_class_id}`,
        name: `No. ${lc.name} (GT)`,
        field: `class_gt_${lc.label_class_id}`,
        sortable: true,
        type: 'number',
        formatter: spinnerOrValue,
    }))

    return [
        checkboxSelector.current.getColumnDefinition(),
        { id: 'thumbnail', name: '',         field: 'image_id',  sortable: false, formatter: thumbnailFormatter },
        { id: 'name',      name: 'Name',     field: 'name',      sortable: true },
        { id: 'width',     name: 'Width',    field: 'width',     sortable: true },
        { id: 'height',    name: 'Height',   field: 'height',    sortable: true },
        { id: 'total',     name: 'Total Objects', field: 'total_objects', sortable: true, formatter: spinnerOrValue },
        { id: 'unlabeled', name: 'Unlabeled',     field: 'unlabeled',    sortable: true, formatter: spinnerOrValue },
        ...perClassCols,
        { id: 'actions',   name: '',         field: 'image_id',  sortable: false, formatter: actionsFormatter },
    ]
}, [labelClasses, projectId, navigate])
```

**Dataset builder:**
```tsx
const dataset = useMemo(() => images.map(img => {
    const s = statsByImageId[img.image_id]   // null = still loading
    const row: Record<string, unknown> = {
        id: img.image_id,
        image_id: img.image_id,
        name: img.name,
        width: img.base_width,
        height: img.base_height,
        total_objects: s?.total_objects ?? null,
        unlabeled: s?.unlabeled_count ?? null,
    }
    for (const lc of labelClasses) {
        row[`class_gt_${lc.label_class_id}`] = s ? (s.per_class_counts[lc.label_class_id] ?? 0) : null
    }
    return row
}), [images, labelClasses, statsByImageId])
```

**Column rebuild when `labelClasses` or `selectedIds` changes:**
```tsx
useEffect(() => {
    if (!gridRef.current) return
    const cols = buildColumns(selectedIds.size)
    gridRef.current.slickGrid.setColumns(cols)
}, [labelClasses, selectedIds.size, buildColumns])
```

**Grid options:**
```tsx
const gridOptions: GridOption = {
    enableAutoResize: true,
    enableCheckboxSelector: true,
    enableRowSelection: true,
    rowSelectionOptions: { selectActiveRow: false },
    checkboxSelector: { hideInFilterHeaderRow: false },
    rowHeight: 64,
    forceFitColumns: true,
    autoResize: { container: '#images-container' },
}
```

**Render (action bar below table):**
```tsx
return (
    <section>
        <h5>Images</h5>
        <div id="images-container" style={{ height: Math.max(200, images.length * 64 + 60) }}>
            <SlickgridReact
                gridId="images-grid"
                columnDefinitions={buildColumns(selectedIds.size)}
                gridOptions={gridOptions}
                dataset={isLoading ? [] : dataset}
                onReactGridCreated={e => onGridReady(e.detail)}
            />
        </div>
        {selectedIds.size > 0 && (
            <div className="d-flex gap-2 mt-2">
                <Button variant="outline-secondary" size="sm"
                    onClick={() => console.log('export', [...selectedIds])}>
                    Export annotations from {selectedIds.size} image{selectedIds.size > 1 ? 's' : ''}
                </Button>
                <Button variant="danger" size="sm"
                    onClick={() => setShowDeleteModal(true)}>
                    Delete {selectedIds.size} image{selectedIds.size > 1 ? 's' : ''}
                </Button>
            </div>
        )}
        <ConfirmationModal
            show={showDeleteModal}
            message={`Permanently delete ${selectedIds.size} image(s) and all their objects?`}
            onConfirm={handleDeleteImages}
            onCancel={() => setShowDeleteModal(false)}
        />
    </section>
)
```

---

### 4.8 `ConfirmationModal.tsx`

Reusable confirmation dialog (Bootstrap `Modal`):
```tsx
interface ConfirmationModalProps {
    show: boolean
    message: string
    onConfirm: () => void
    onCancel: () => void
}

export default function ConfirmationModal({ show, message, onConfirm, onCancel }: ConfirmationModalProps) {
    return (
        <Modal show={show} onHide={onCancel} centered>
            <Modal.Header closeButton><Modal.Title>Confirm</Modal.Title></Modal.Header>
            <Modal.Body>{message}</Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={onCancel}>Cancel</Button>
                <Button variant="danger" onClick={onConfirm}>Confirm</Button>
            </Modal.Footer>
        </Modal>
    )
}
```

---

### 4.9 File Layout

Sub-components live under `src/components/projectPage/` to avoid cluttering the shared `components/` folder:

```
src/
  routes/
    projectPage.tsx           ← top-level page, data fetching only
  components/
    ConfirmationModal.tsx      ← shared, reusable
    projectPage/
      MetadataSection.tsx
      LabelClassesTable.tsx
      ImagesTable.tsx
```

---

### 4.10 Slickgrid Formatter Reference

Formatters used in this project follow the signature from the `slickgrid-react` `Column` type:
```ts
type Formatter = (
    row: number,
    cell: number,
    value: any,
    columnDef: Column,
    dataContext: any,
    grid?: SlickGrid
) => string | HTMLElement
```

- **String return**: HTML string rendered via `innerHTML` inside the cell. Safe for static content; avoid putting user-supplied text here without escaping.
- **HTMLElement return**: DOM node appended directly. Use this when attaching event listeners (e.g., delete/action buttons) to avoid the inline-handler security anti-pattern.
- **Spinner pattern** (from QuickAnnotator reference):
  ```ts
  `<span class="spinner-border spinner-border-sm" role="status"></span>`
  ```
- **Lazy image pattern** (from QuickAnnotator reference): render spinner + hidden img; use `onload`/`onerror` inline handlers to swap visibility.
- **Color swatch**: render a `<span>` with `background: <color>` inline style.

---

### 4.11 Styling
- Bootstrap 5 classes for layout (`d-flex`, `gap-4`, `py-3`)
- `@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css` for grid theme
- `rowHeight: 64` for the Images table (to fit 56px thumbnail), `rowHeight: 40` for Label Classes
- Container `<div>` heights are computed dynamically from row count to avoid a fixed scrollable grid

---

## Phase 5: Implementation Order

1. **DB schema migrations** — `creation_ts` on project
2. **Backend endpoints** — stats, settings, images, image summary, thumbnail, export, project update
3. **Regenerate TypeScript client** — run `npm run openapi-ts` in `patchsorter/client/`
4. **Install slickgrid** — `npm install slickgrid-react @slickgrid-universal/common` in `patchsorter/client/`
5. **Add route** — update `main.tsx` with `/project/:projectId/project`
6. **Build `ConfirmationModal`** — shared, needed by both tables
7. **Build `MetadataSection`** — Bootstrap `<Table>`, spinner-per-cell
8. **Build `LabelClassesTable`** — `SlickgridReact` + `CheckboxSelectColumn` + bulk delete
9. **Build `ImagesTable`** — `SlickgridReact` + `useQueries` + dynamic columns + `setColumns()` rebuild
10. **Build `ProjectPage`** route component — wires all three sections together
11. **Wire up Navigation breadcrumb** — add "Project" link in `Navigation.tsx`
12. **Test all flows end-to-end**

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
| `patchsorter/client/src/routes/projectPage.tsx` | **Create**: thin page component, data fetching only |
| `patchsorter/client/src/components/ConfirmationModal.tsx` | **Create**: shared Bootstrap `Modal` |
| `patchsorter/client/src/components/projectPage/MetadataSection.tsx` | **Create** |
| `patchsorter/client/src/components/projectPage/LabelClassesTable.tsx` | **Create** |
| `patchsorter/client/src/components/projectPage/ImagesTable.tsx` | **Create** |
| `patchsorter/client/src/main.tsx` | Modify: add `/project/:projectId/project` route |
| `patchsorter/client/src/components/Navigation.tsx` | Modify: add "Project" breadcrumb link |
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate |
| `patchsorter/client/package.json` | Modify: add `slickgrid-react`, `@slickgrid-universal/common` |
