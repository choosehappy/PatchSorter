# Upload Wizard – Implementation Plan

## Overview

Add a multi-step Upload Wizard as a Bootstrap `<Modal>` on the Project Page. The wizard supports two upload approaches:

1. **Step-by-Step** — Upload images, masks, and labels in separate steps, then review.
2. **CSV File List** — Upload a single CSV with `filepath` and `geojson_filepath` columns, then review.

The wizard is triggered by the existing "Enter Upload Wizard" button in `ActionsFooter`. The modal displays a dynamic step indicator that updates based on the chosen approach. The final step shows a unified SlickGrid review table built lazily from wizard refs.

---

## Reference Design

| Document Section | Content |
|------------------|---------|
| 2.4.3 (Usecase6) | Step-by-step upload flow — select files, confirm details, monitor progress |
| 2.4.4 (Usecase7) | CSV File List upload — bulk upload via CSV with `filepath` + `geojson_filepath` |

---

## Current State

| File | Current state |
|------|---------------|
| `ActionsFooter.tsx:65-71` | "Enter Upload Wizard" button is a stub (`console.log`) |
| `ProjectPage` | No upload state, no modal rendering |
| Backend | No upload API endpoints exist |
| Frontend | No upload components, hooks, or file input elements exist |

---

## Architecture

### Data Flow

```
ProjectPage
  state: showUploadWizard: boolean
       │
       ├─ true  ──► <UploadWizardModal projectId={…} onClose={…} />
       │
       └─ false ──► (no modal rendered)

UploadWizardModal
  refs (useUpload hook):
    approach: 'stepByStep' | 'csvFileList' | null
    currentStep: number (1–5)
    images: File[]
    masks: File[]
    labels: File[]
    csvFile: File | null

  Step 1: <StepApproachSelection> — radio buttons
       │
       ├─ stepByStep  ──► Step 2 → Step 3 → Step 4 → Step 5 (Review)
       │                    UploadImages  UploadMasks  UploadLabels
       │
       └─ csvFileList ──► Step 2 → Step 3 (Review)
                            UploadFileList

  Step 5 (Review): <StepReview>
    reads approach, images, masks, labels, csvFile from refs
    renders unified SlickGrid with lazy data
    "Upload" button triggers API call
```

### Ref-based approach for Review step

The Review step reads directly from wizard refs rather than storing a separate `reviewData` object. This avoids data duplication and ensures the grid always reflects the current wizard state. When the user navigates back and changes files, the grid re-renders automatically.

---

## File Layout

```
patchsorter/client/src/
  components/
    projectPage/
      UploadWizardModal.tsx        ← Modal shell, wizard state, step navigation
      UploadWizardModal.css        ← Modal styling
      UploadStepIndicator.tsx      ← Dynamic step progress bar (bolds current step)
      StepApproachSelection.tsx    ← Step 1: radio buttons
      StepUploadImages.tsx         ← Step 2a: drag-drop image files
      StepUploadMasks.tsx          ← Step 2b: drag-drop mask files
      StepUploadLabels.tsx         ← Step 2c: drag-drop label files
      StepUploadFileList.tsx       ← Step 2 (CSV): CSV file upload
      StepReview.tsx               ← Step 5: unified SlickGrid review table
      useUpload.ts                 ← Wizard state management hook with refs
```

---

## Step 1: Create `useUpload.ts` Hook

**File:** `patchsorter/client/src/components/projectPage/useUpload.ts`

A custom hook returning refs (not state) so that child components can mutate file lists without causing re-renders, and the Review step can read live values.

```typescript
interface UploadWizardState {
    approach: React.MutableRefObject<'stepByStep' | 'csvFileList' | null>
    currentStep: React.MutableRefObject<number>
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    labels: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>
    
    // Actions
    setApproach: (a: 'stepByStep' | 'csvFileList') => void
    nextStep: () => void
    prevStep: () => void
    addImages: (files: File[]) => void
    addMasks: (files: File[]) => void
    addLabels: (files: File[]) => void
    setCsvFile: (file: File | null) => void
    reset: () => void
}
```

**Key behaviors:**
- `reset()` clears all refs and sets `currentStep` to 1
- `nextStep()` advances `currentStep`, auto-advancing if the current step has no files selected (e.g., skipping empty upload steps)
- `prevStep()` goes back one step
- File refs are mutable arrays — `addImages` calls `images.current.push(...files)`

---

## Step 2: Create `UploadStepIndicator.tsx`

**File:** `patchsorter/client/src/components/projectPage/UploadStepIndicator.tsx`

A horizontal step progress bar that renders step labels as text segments. The current step is **bolded**, previous steps are grayed, and future steps are muted.

**Props:**

```typescript
interface StepIndicatorProps {
    steps: string[]  // e.g. ['Choose Approach', 'Upload Images', 'Upload Masks', 'Upload Labels', 'Review']
    currentStep: number  // 1-indexed
}
```

**Rendering logic:**

```tsx
// Steps: 1. Choose Approach, 2. Upload Images, 3. Upload Masks, 4. Upload Labels, 5. Review
//         ^bold                              ^normal                        ^normal
```

Each step segment renders as:
```
{stepNumber}. {label}
```

With conditional styling:
- `fontWeight: currentStepIndex === segmentIndex ? 'bold' : 'normal'`
- `color: segmentIndex < currentStepIndex ? '#6c757d' : segmentIndex === currentStepIndex ? '#0d6efd' : '#adb5bd'`
- Separator: `•` between steps

**Two step arrays:**

| Approach | Steps |
|----------|-------|
| Step-by-Step | `['Choose Approach', 'Upload Images', 'Upload Masks', 'Upload Labels', 'Review']` |
| CSV File List | `['Choose Approach', 'Upload File List', 'Review']` |

---

## Step 3: Create `StepApproachSelection.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx`

Step 1: two radio button options.

**Options:**
1. **Step by Step** — "Upload images, masks, and labels individually"
2. **CSV File List** — "Upload a CSV with filepath and geojson_filepath columns"

**Props:**

```typescript
interface StepApproachSelectionProps {
    onSelect: (approach: 'stepByStep' | 'csvFileList') => void
}
```

**UI:** Bootstrap `Form.Check` radio buttons in a vertical stack. Selection is immediate (no "Next" button needed — the step indicator updates live).

---

## Step 4: Create Upload Steps

### `StepUploadImages.tsx`

Drag-drop zone for image files. Accepts common image extensions (`.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`). Shows file count and total size.

**Props:**

```typescript
interface StepUploadImagesProps {
    files: File[]
    onAddFiles: (files: File[]) => void
}
```

**Features:**
- Drag-and-drop with visual feedback (highlight border)
- Click-to-browse file input
- File list preview below the drop zone (name, size)
- Remove button per file

### `StepUploadMasks.tsx`

Same as `StepUploadImages` but for mask files (masks are typically binary or grayscale images).

### `StepUploadLabels.tsx`

Same as `StepUploadImages` but for label files (GeoJSON or other annotation formats).

### `StepUploadFileList.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepUploadFileList.tsx`

Single CSV file upload zone.

**Props:**

```typescript
interface StepUploadFileListProps {
    file: File | null
    onFile: (file: File | null) => void
}
```

**Features:**
- Drag-drop zone for CSV file
- Parses CSV on selection (client-side) to validate format
- Shows preview: row count, first 5 rows as a small table
- Validates that first two columns are named `filepath` and `geojson_filepath`
- Shows validation errors if format is incorrect

---

## Step 5: Create `StepReview.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepReview.tsx`

A single unified SlickGrid that displays all upload data from wizard refs.

**Props:**

```typescript
interface StepReviewProps {
    approach: 'stepByStep' | 'csvFileList' | null
    images: File[]
    masks: File[]
    labels: File[]
    csvFile: File | null
    onUpload: () => void
    isUploading: boolean
}
```

### Grid columns (dynamic based on approach)

**Step-by-Step flow:**

| Column | Field | Formatter |
|--------|-------|-----------|
| Type | `type` | Text: "Image", "Mask", "Label" |
| File | `name` | Text |
| Size | `size` | Formatted bytes (e.g., "1.2 MB") |
| Status | `status` | Green badge "Ready" |

**CSV File List flow:**

| Column | Field | Formatter |
|--------|-------|-----------|
| Row | `rowIndex` | Number (1-indexed) |
| filepath | `filepath` | Text (truncated with ellipsis) |
| geojson_filepath | `geojson` | Text (truncated with ellipsis) |
| Status | `error` | Empty string or red error text |

### Dataset building from refs

```typescript
// Inside StepReview render
const dataset = useMemo(() => {
    if (approach === 'csvFileList') {
        // Parse csvFile as text, split into rows
        const rows: ReviewRow[] = []
        const text = csvFile?.name ? '' : ''  // would use FileReader or cached text
        // ... parse CSV, build rows
        return rows
    }
    
    const rows: ReviewRow[] = []
    for (const f of images) rows.push({ type: 'Image', name: f.name, size: f.size, status: 'ready' })
    for (const f of masks)  rows.push({ type: 'Mask',  name: f.name, size: f.size, status: 'ready' })
    for (const f of labels) rows.push({ type: 'Label', name: f.name, size: f.size, status: 'ready' })
    return rows
}, [approach, images, masks, labels, csvFile])
```

### Grid options

```typescript
const gridOptions: GridOption = {
    enableAutoResize: true,
    enableColoredGroups: false,
    rowHeight: 32,
    forceFitColumns: true,
    autoResize: { container: '#upload-review-container' },
}
```

### Upload button

A "Upload" button below the grid that triggers the backend API call. Shows a spinner while uploading.

---

## Step 6: Create `UploadWizardModal.tsx`

**File:** `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx`

The modal shell that orchestrates the wizard.

**Props:**

```typescript
interface UploadWizardModalProps {
    projectId: number
    onClose: () => void
}
```

**Modal structure:**

```tsx
<Modal show={true} onHide={onClose} size="lg" centered>
    <Modal.Header closeButton>
        <Modal.Title>Upload Images</Modal.Title>
    </Modal.Header>
    <Modal.Body>
        <UploadStepIndicator steps={steps} currentStep={currentStep} />
        
        {approach === null && <StepApproachSelection onSelect={setApproach} />}
        
        {approach === 'stepByStep' && currentStep === 2 && (
            <StepUploadFiles type="images" files={images} onAddFiles={addImages} />
        )}
        {approach === 'stepByStep' && currentStep === 3 && (
            <StepUploadFiles type="masks" files={masks} onAddFiles={addMasks} />
        )}
        {approach === 'stepByStep' && currentStep === 4 && (
            <StepUploadFiles type="labels" files={labels} onAddFiles={addLabels} />
        )}
        
        {approach === 'csvFileList' && currentStep === 2 && (
            <StepUploadFileList file={csvFile} onFile={setCsvFile} />
        )}
        
        {currentStep === 5 && (
            <StepReview
                approach={approach}
                images={images}
                masks={masks}
                labels={labels}
                csvFile={csvFile}
                onUpload={handleUpload}
                isUploading={isUploading}
            />
        )}
    </Modal.Body>
    <Modal.Footer>
        {currentStep > 1 && (
            <Button variant="secondary" onClick={prevStep}>Back</Button>
        )}
        {currentStep < 5 && (
            <Button variant="primary" onClick={nextStep} disabled={!canProceed}>Next</Button>
        )}
        {currentStep === 5 && (
            <Button variant="primary" onClick={handleUpload} disabled={isUploading}>
                {isUploading ? 'Uploading...' : 'Upload'}
            </Button>
        )}
        {currentStep === 5 && !isUploading && (
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
        )}
    </Modal.Footer>
</Modal>
```

**Step array determination:**

```typescript
const steps = approach === 'csvFileList'
    ? ['Choose Approach', 'Upload File List', 'Review']
    : ['Choose Approach', 'Upload Images', 'Upload Masks', 'Upload Labels', 'Review']
```

---

## Step 7: Wire up `ActionsFooter.tsx`

**File:** `patchsorter/client/src/components/projectPage/ActionsFooter.tsx`

1. Add `onOpenUploadWizard?: () => void` to `ActionsFooterProps`
2. Replace `console.log('Enter Upload Wizard not implemented yet')` with `onOpenUploadWizard?.()`

---

## Step 8: Wire up `ProjectPage`

**File:** `patchsorter/client/src/routes/projectPage.tsx`

1. Add state: `const [showUploadWizard, setShowUploadWizard] = useState(false)`
2. Pass `onOpenUploadWizard={() => setShowUploadWizard(true)}` to `ActionsFooter`
3. Conditionally render `<UploadWizardModal>` when `showUploadWizard` is true

---

## Backend Endpoints Needed

These endpoints do not exist yet. They are required for the Upload Wizard to function.

### 1. `POST /api/v1/projects/{project_id}/upload/images`

Upload image files (multipart/form-data).

**Request:**
```
Content-Type: multipart/form-data

files: [File, File, ...]
```

**Response:**
```json
{
    "job_id": "abc123",
    "status": "pending",
    "message": "Upload job created"
}
```

### 2. `POST /api/v1/projects/{project_id}/upload/masks`

Upload mask files (multipart/form-data). Same request/response as above.

### 3. `POST /api/v1/projects/{project_id}/upload/labels`

Upload label files (multipart/form-data). Same request/response as above.

### 4. `POST /api/v1/projects/{project_id}/upload/csv`

Upload CSV file list.

**Request:**
```
Content-Type: multipart/form-data

csv_file: File
```

**Response:**
```json
{
    "job_id": "def456",
    "status": "pending",
    "rows": [
        { "filepath": "path/to/image.tif", "geojson_filepath": "path/to/image.geojson", "status": "ok" },
        { "filepath": "path/to/bad.tif", "geojson_filepath": "", "status": "error", "error": "File not found" }
    ],
    "summary": { "total": 10, "ok": 8, "error": 2 }
}
```

### 5. `GET /api/v1/projects/{project_id}/jobs/{job_id}`

Poll job status.

**Response:**
```json
{
    "job_id": "abc123",
    "status": "processing",  // "pending" | "processing" | "completed" | "failed"
    "progress": 0.45,        // 0.0 to 1.0
    "message": "Processing image 5 of 10",
    "errors": []
}
```

---

## TypeScript Client Regeneration

After backend endpoints are implemented:

1. Run `npm run openapi-ts` in `patchsorter/client/`
2. New types: `UploadJobResponse`, `CsvUploadResponse`, `JobStatusResponse`
3. New SDK functions: `uploadImagesProjectsProjectIdUploadImagesPost`, `uploadMasksProjectsProjectIdUploadMasksPost`, `uploadLabelsProjectsProjectIdUploadLabelsPost`, `uploadCsvProjectsProjectIdUploadCsvPost`, `getJobProjectsProjectIdJobsJobIdGet`

---

## CSS Styling

**File:** `patchsorter/client/src/components/projectPage/UploadWizardModal.css`

```css
/* Drag-drop zone */
.upload-dropzone {
    border: 2px dashed #dee2e6;
    border-radius: 8px;
    padding: 32px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background-color 0.2s;
}
.upload-dropzone.drag-over {
    border-color: #0d6efd;
    background-color: #f8f9ff;
}
.upload-dropzone:hover {
    border-color: #6c757d;
}

/* File list */
.upload-file-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-radius: 4px;
    background: #f8f9fa;
    margin-bottom: 4px;
}
.upload-file-item .file-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    margin-right: 12px;
}

/* Step indicator */
.upload-step-segment {
    cursor: default;
    transition: color 0.2s;
}
.upload-step-segment.current {
    font-weight: 700;
}
.upload-step-segment.done {
    color: #6c757d;
}
.upload-step-segment.upcoming {
    color: #adb5bd;
}

/* Review grid container */
#upload-review-container {
    max-height: 400px;
    overflow-y: auto;
}
```

---

## Implementation Order

1. **Create `useUpload.ts`** — hook with refs and actions
2. **Create `UploadStepIndicator.tsx`** — dynamic step progress bar
3. **Create `StepApproachSelection.tsx`** — radio button step
4. **Create `StepUploadImages.tsx`**, `StepUploadMasks.tsx`, `StepUploadLabels.tsx` — drag-drop upload steps
5. **Create `StepUploadFileList.tsx`** — CSV upload step with validation
6. **Create `StepReview.tsx`** — unified SlickGrid review table
7. **Create `UploadWizardModal.tsx`** — modal shell orchestrating all steps
8. **Create `UploadWizardModal.css`** — modal and component styles
9. **Wire up `ActionsFooter.tsx`** — add `onOpenUploadWizard` prop
10. **Wire up `ProjectPage`** — add `showUploadWizard` state, render modal
11. **Implement backend endpoints** (separate PR/phase)
12. **Regenerate TypeScript client** (after backend changes)
13. **Test all flows end-to-end**

---

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/client/src/components/projectPage/useUpload.ts` | **Create** — wizard state hook with refs |
| `patchsorter/client/src/components/projectPage/UploadStepIndicator.tsx` | **Create** — step progress bar |
| `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx` | **Create** — radio button step |
| `patchsorter/client/src/components/projectPage/StepUploadImages.tsx` | **Create** — image file upload |
| `patchsorter/client/src/components/projectPage/StepUploadMasks.tsx` | **Create** — mask file upload |
| `patchsorter/client/src/components/projectPage/StepUploadLabels.tsx` | **Create** — label file upload |
| `patchsorter/client/src/components/projectPage/StepUploadFileList.tsx` | **Create** — CSV upload with validation |
| `patchsorter/client/src/components/projectPage/StepReview.tsx` | **Create** — unified SlickGrid review |
| `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx` | **Create** — modal shell |
| `patchsorter/client/src/components/projectPage/UploadWizardModal.css` | **Create** — modal styling |

## Files to Modify

| File | Action |
|------|--------|
| `patchsorter/client/src/components/projectPage/ActionsFooter.tsx` | Add `onOpenUploadWizard` prop; wire button to callback |
| `patchsorter/client/src/routes/projectPage.tsx` | Add `showUploadWizard` state; render `<UploadWizardModal>` |

## Files to Regenerate (after backend)

| File | Action |
|------|--------|
| `patchsorter/client/src/api_client/types.gen.ts` | Regenerate with new upload types |
| `patchsorter/client/src/api_client/sdk.gen.ts` | Regenerate with new upload functions |

## Backend Files to Create/Modify (future)

| File | Action |
|------|--------|
| `patchsorter/api/v1/upload/routes.py` | **Create** — upload endpoints |
| `patchsorter/api/v1/upload/models.py` | **Create** — upload response models |
| `patchsorter/api/v1/main.py` | Modify — include upload router |
