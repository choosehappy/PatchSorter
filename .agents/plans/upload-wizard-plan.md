# Upload Wizard – Implementation Plan

## Overview

Add a multi-step Upload Wizard as a Bootstrap `<Modal>` on the Project Page. The wizard supports two upload approaches:

1. **Step-by-Step** — Upload images, masks, and patch CSV (patch_uuid, gt_label, centroid_x, centroid_y) in separate steps, then review.
2. **CSV File List** — Upload a single CSV describing file locations on the server, then review.

The wizard is triggered by the existing "Enter Upload Wizard" button in `ActionsFooter`. The modal displays a dynamic step indicator that updates based on the chosen approach. When the user reaches the review step, it calls the `/validate/` endpoint and displays the results directly.

**Reference implementation:** The old jQuery-based upload wizard at `patchsorter/static/js/ps-upload.js` (commit `77456834`) provides the complete UX spec. This plan maps its 7-step flow, per-type toggles, and validation logic to React.

---

## Reference Design

| Document Section | Content |
|------------------|---------|
| 2.4.3 (Usecase6) | Step-by-step upload flow — select files, confirm details, monitor progress |
| 2.4.4 (Usecase7) | CSV File List upload — bulk upload via CSV with `filepath` + `geojson_filepath` |
| `ps-upload.js` (commit 77456834) | Complete 7-step upload wizard with per-type toggles, path validation, session-based uploads |

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
       ├─ true  ──► <UploadWizardModal projectId={…} onClose={…} onSessionOpen={…} />
       │
       └─ false ──► (no modal rendered)

UploadWizardModal
   state (useUpload hook — drives re-renders):
     approach: 'stepByStep' | 'csvFileList' | null
     currentStep: number (0–6)
     session: string | null        // null until user first proceeds from step 0
     includeMasks: boolean
     includeCSV: boolean
     isFolderByType: Record<uploadType, boolean>  // controls toggle UI per type
   refs (useUpload hook — mutated without re-renders, read at validation time):
     images: File[]
     masks: File[]
     csvLabels: File[]
     csvFile: File | null
     pathsByType: Record<uploadType, string>    // server paths for "Load Folder" mode

   Step 0: <StepApproachSelection> — radio buttons
        │
        ├─ stepByStep  ──► Step 1 → Step 2 → Step 3 → Step 5 (Review)
        │                    UploadImages  UploadMasks  UploadCSVs
        │                    (each with toggle: Upload Files / Load Folder)
        │
        └─ csvFileList ──► Step 4 → Step 5 (Review)
                             UploadFileList

   Step 5 (Review): <StepReview>
     calls POST .../validate/ with file data from refs
     receives ReviewRow[] response
     renders unified review table (Image, Mask, CSV, Error, Status columns)
     "Process" button triggers API call
```

### Review step data flow

The Review step fetches data directly from the `/validate/` endpoint when the user navigates to it. It does **not** use wizard refs for review data. The flow is:

1. User clicks "Next" from the last upload step
2. Modal calls `POST /api/v1/projects/{project_id}/upload/{session}/validate/` with file paths from refs (for file-drop mode) or folder paths (for folder mode)
3. Server returns `ReviewRow[]` with status per row
4. Modal stores results in local state (`reviewData`)
5. `<StepReview>` renders the table from `reviewData`

**Process button behavior:** The process button is **never blocked** by errors. It always remains enabled when there are at least one `ok` row. The error warning text changes from "Fix the issues before processing" to "Consider fixing the issues before processing". When the user clicks Process, only rows with `status === 'ok'` are sent to the backend (the `status` and `error` fields are stripped — only `image`, `mask`, `csv` are sent).

### Upload Types (from `ps-upload.js`)

| Type | Accepts | Purpose |
|------|---------|---------|
| `image` | `image/*` | Scan images (WSI tiles) |
| `mask` | `.geojson` | Annotation mask files (GeoJSON format) |
| `csv` | `.csv` | Label CSV files |

### Per-Type Toggle: "Upload Files" vs "Load Folder"

Each upload step (images, masks, CSVs) has a toggle between two modes:

- **Upload Files** — Client-side drag-drop zone (dropzone) for local files
- **Load Folder** — Text input for server-side directory paths (remote files)

This is a critical feature from the old wizard that is **missing** from the original plan. The toggle controls which UI is shown per upload type.

### Optional Inputs

Masks and CSV uploads are optional. Each has a toggle (`includeMasks`, `includePatchCsv`) that hides/shows the upload step entirely.

**Toggle Mutex:** Only one toggle can be "declined" (turned OFF). When the user turns one toggle OFF, the other toggle is **enabled + disabled** (grayed out, unclickable) to show it is the remaining valid option. If the user turns the remaining ON toggle back OFF, the other toggle becomes ON+disabled again. This is enforced via `disabledMask` and `disabledPatchCsv` state booleans.

### Session Management via Ray Actor

The upload session is managed by a **Ray actor** that:
- Uses Python's `tempfile.TemporaryDirectory` to create a temp directory for the session, stored as `self._tmpdir`
- Exposes a `cleanup()` remote method that calls `self._tmpdir.cleanup()`, deleting all temp files
- Session UUID is **server-side generated** (not client-side)

**Session creation is lazy.** The client does **not** call `openSession()` on modal mount. The session is created the first time the user clicks "Next" from step 0 (i.e., after selecting an approach, when `session` is `null`). This avoids leaking Ray actors when the user opens and immediately closes the modal without uploading anything.

The client calls `POST /api/v1/projects/{project_id}/upload/open/` to create the actor and receive the session UUID. All subsequent endpoints use this session ID as a URL path segment.

**Garbage Collection:** A separate `UploadSessionGarbageCollector` Ray actor runs as a named singleton at app startup. When a session actor is created, its UUID and creation timestamp are registered with the GC actor via `gc.register.remote(session_id, actor_handle)`. The GC runs a periodic cleanup task (every 5 minutes) that identifies session actors whose age exceeds the configured TTL (default: 1 hour) and cleans them up:

1. Calls `actor.cleanup.remote()` to invoke `self._tmpdir.cleanup()`, deleting the temp directory
2. Calls `ray.kill(actor, no_restart=True)` to destroy the actor
3. Removes the session from its registry

The GC actor itself is a named actor (`@ray.remote(name="upload_session_gc")`) started once at app init.

### Path Validation Before Upload

Before reaching the review step, the wizard sends selected paths to a `/validate/` endpoint. The server checks file existence and returns a `ReviewRow[]` with status (ok/error) per row. The review table displays these results.

---

## File Layout

```
patchsorter/client/src/
  components/
    projectPage/
      UploadWizardModal.tsx        ← Modal shell, wizard state, step navigation
      UploadWizardModal.css        ← Modal styling
      UploadStepIndicator.tsx      ← Dynamic step progress bar (bolds current step)
      StepApproachSelection.tsx    ← Step 0: radio buttons (step-by-step vs file list)
      StepUploadImages.tsx         ← Step 1: drag-drop or server path for images
      StepUploadMasks.tsx          ← Step 2: drag-drop or server path for masks
      StepUploadPatchCsv.tsx           ← Step 3: drag-drop or server path for patch CSV
      StepUploadFileList.tsx       ← Step 4: CSV file list upload
      StepReview.tsx               ← Step 5: unified review table
      StepComplete.tsx             ← Step 6: upload complete screen
      useUpload.ts                 ← Wizard state management hook with refs
```

---

## Step 0: Create `useUpload.ts` Hook

**File:** `patchsorter/client/src/components/projectPage/useUpload.ts`

A custom hook that separates UI-driving values (returned as `useState`) from file data that is only read at validation time (stored as `useRef`). This avoids unnecessary re-renders when files are added.

```typescript
interface UploadWizardState {
    // React state — changes here trigger re-renders
    approach: 'stepByStep' | 'csvFileList' | null
    currentStep: number              // 0–6 (global numbering, see step table)
    session: string | null           // null until user first proceeds from step 0
    includeMasks: boolean
    includeCSV: boolean
    isFolderByType: Record<string, boolean>  // true = "Load Folder" mode for that type

    // Refs — mutated without re-renders; read at validation time
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    csvLabels: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>
    pathsByType: React.MutableRefObject<Record<string, string>>  // server paths per type

    // Actions
    openSession: () => Promise<void>   // called lazily; safe to call multiple times
    setApproach: (a: 'stepByStep' | 'csvFileList') => void
    nextStep: () => void
    prevStep: (targetStep?: number) => void
    prevReviewStep: () => void         // returns to last upload step before review (approach-aware)
    addImages: (files: File[]) => void
    addMasks: (files: File[]) => void
    addCSVLabels: (files: File[]) => void
    setCsvFile: (file: File | null) => void
    reset: () => void
}
```

**Key behaviors:**
- `openSession()` calls `POST /api/v1/projects/{project_id}/upload/open/` and stores the returned session ID in state. Called by `nextStep()` when leaving step 0 if `session` is `null`; safe to call multiple times (no-ops if session already set)
- `reset()` clears all refs, resets all state to initial values, and sets `currentStep` to 0
- `nextStep()`: (1) calls `openSession()` if leaving step 0 and session is null; (2) advances `currentStep` according to approach — for CSV approach, jumps from 0 to 4; for step-by-step, auto-skips step 2 if `!includeMasks` and step 3 if `!includeCSV`
- `prevStep(targetStep?)` goes back one step or jumps to a specific step number
- `prevReviewStep()` goes back from step 5 (Review) to the correct last upload step: step 4 for CSV approach; step 3, 2, or 1 for step-by-step depending on which optional steps are included
- File refs are mutable arrays — `addImages` calls `images.current.push(...files)`
- `pathsByType` stores server directory paths per upload type (for "Load Folder" mode)

---

## Step 1: Create `UploadStepIndicator.tsx`

**File:** `patchsorter/client/src/components/projectPage/UploadStepIndicator.tsx`

A horizontal step progress bar that renders step labels as text segments. The current step is **bolded**, previous steps are grayed, and future steps are muted.

**Props:**

```typescript
interface StepIndicatorProps {
    steps: string[]  // e.g. ['Choose Approach', 'Upload Images', 'Upload Masks', 'Upload CSVs', 'Review', 'Complete']
    currentStep: number  // 0-indexed
}
```

**Rendering logic:**

Each step segment renders as:
```
{stepNumber}. {label}
```

With conditional styling:
- `fontWeight: currentStepIndex === segmentIndex ? 'bold' : 'normal'`
- `color: segmentIndex < currentStepIndex ? '#6c757d' : segmentIndex === currentStepIndex ? '#0d6efd' : '#adb5bd'`
- Separator: `•` between steps

**Step arrays for the step indicator:**

| Approach | Step indicator labels |
|----------|-----------------------|
| Step-by-Step | `['Upload Method', 'Upload Scan Images', 'Upload Masks', 'Upload CSVs', 'Review Data', 'Upload Complete']` |
| CSV File List | `['Upload Method', 'Upload File List', 'Review Data', 'Upload Complete']` |

**Global `currentStep` numbering** (shared across both approaches — the step indicator maps this to a position in the approach-specific label array):

| `currentStep` | Component | Approach |
|---------------|-----------|----------|
| 0 | `StepApproachSelection` | Both |
| 1 | `StepUploadImages` | Step-by-Step only |
| 2 | `StepUploadMasks` | Step-by-Step only |
| 3 | `StepUploadCSVs` | Step-by-Step only |
| 4 | `StepUploadFileList` | CSV File List only |
| 5 | `StepReview` | Both |
| 6 | `StepComplete` | Both |

For the CSV approach, `nextStep()` from step 0 jumps directly to step 4 (skipping steps 1–3).

---

## Step 2: Create `StepApproachSelection.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx`

Step 0: two radio button options.

**Options:**
1. **Step-by-step** — "Upload images, masks, and patch CSV (patch_uuid, gt_label, centroid_x, centroid_y) individually"
2. **File List** — "Upload a CSV with 3 columns: image filename, mask filename, patch_csv filename (absolute paths on the server)"

**Props:**

```typescript
interface StepApproachSelectionProps {
    onSelect: (approach: 'stepByStep' | 'csvFileList') => void
}
```

**UI:** Bootstrap `Form.Check` radio buttons in a vertical stack. Selection is immediate (no "Next" button needed — the step indicator updates live).

---

## Step 3: Create Upload Steps

### `StepUploadImages.tsx`

Drag-drop zone for image files **or** server path input, controlled by a per-type toggle.

**Props:**

```typescript
interface StepUploadImagesProps {
    files: File[]
    onAddFiles: (files: File[]) => void
    serverPath: string
    onServerPathChange: (path: string) => void
    useDropzone: boolean
    onToggleDropzone: (useDropzone: boolean) => void
    isFolder: boolean  // whether the current mode is "Load Folder"
}
```

**Features:**
- Toggle: "Upload Files" (dropzone) vs "Load Folder" (text input)
- If dropzone: drag-and-drop with visual feedback, click-to-browse, file list preview
- If folder: text input for server directory path, "Next" enabled when non-empty
- Accepts: `.tif`, `.tiff`, `.png`, `.jpg`, `.jpeg`, `image/*`

### `StepUploadMasks.tsx`

Same structure as `StepUploadImages` but for GeoJSON annotation mask files.
- **Accepts:** `.geojson` only (not `image/*`)
- **Optional toggle**: "Upload Masks" can be disabled entirely (hides the step)

### `StepUploadCSVs.tsx`

Same as `StepUploadImages` but for patch CSV files.
- **Optional toggle**: "Upload Patch CSV" can be disabled entirely (hides the step)

### `StepUploadFileList.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepUploadFileList.tsx`

Single CSV file upload zone (dropzone only — no "Load Folder" mode).

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
- **Validates 3-column format with required header row**: the CSV must start with a header row `image,mask,csv`, followed by data rows of absolute server paths
- Shows validation errors if the header is missing or columns do not match
- Note: paths in the CSV are absolute paths on the **server hosting the app**, not the client

---

## Step 4: Create `StepReview.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepReview.tsx`

A unified review table that displays validation results from the `/validate/` endpoint.

**Props:**

```typescript
interface StepReviewProps {
    approach: 'stepByStep' | 'csvFileList' | null
    reviewData: ReviewRow[] | null
}
```

`StepReview` is **display-only** — it renders the review table from `reviewData`. Process and Back buttons are rendered exclusively in `Modal.Footer` (see `UploadWizardModal`).

### Review table columns (from `ps-upload.js` `makeResultsRow`)

| Column | Field | Formatter |
|--------|-------|-----------|
| Image | `image` | Text |
| Mask | `mask` | Text |
| CSV | `csv` | Text |
| Error | `error` | Red text if present |
| Status | `status` | Green "ok" or red "error" |

### Review step error handling

The review step displays a warning when there are errors:
```
{errorCount} row{errorCount !== 1 ? 's have' : ' has'} errors. Consider fixing the issues before processing.
```

The process button is **always enabled** when there is at least one `ok` row. When the user clicks Process, only `ok` rows are sent to the backend — error rows are silently excluded.

### Dataset building

```typescript
// reviewData comes directly from the /validate/ endpoint response
// Each row has: image, mask, csv, error, status fields
const dataset = useMemo(() => reviewData ?? [], [reviewData])
```

---

## Step 5: Create `UploadWizardModal.tsx`

**File:** `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx`

The modal shell that orchestrates the wizard.

**Props:**

```typescript
interface UploadWizardModalProps {
    projectId: number
    onClose: () => void
    onSessionOpen: (session: string) => void
}
```

**Session:** `openSession()` is called lazily by `nextStep()` the first time the user leaves step 0 (when `session` is `null`). Nothing happens on modal mount.

**Modal structure:**

```tsx
<Modal show={true} onHide={onClose} size="lg" centered>
    <Modal.Header closeButton>
        <Modal.Title id="upload-step-title">Upload Method</Modal.Title>
    </Modal.Header>
    <Modal.Body>
        <UploadStepIndicator steps={steps} currentStep={currentStep} />
        <p id="upload-step-details">{stepDetails}</p>
        
        {/* Step 0: Approach selection */}
        {approach === null && <StepApproachSelection onSelect={setApproach} />}
        
        {/* Step 1: Upload Images */}
        {approach === 'stepByStep' && currentStep === 1 && (
            <StepUploadImages
                files={images} onAddFiles={addImages}
                serverPath={pathsByType['image']}
                onServerPathChange={(p) => updatePath('image', p)}
                useDropzone={useDropzone['image']}
                onToggleDropzone={(v) => toggleDropzone('image', v)}
                isFolder={isFolderByType['image']}
            />
        )}
        
        {/* Step 2: Upload Masks */}
        {approach === 'stepByStep' && currentStep === 2 && (
            <StepUploadMasks
                files={masks} onAddFiles={addMasks}
                includeMasks={includeMasks} onToggleInclude={setIncludeMasks}
                serverPath={pathsByType['mask']}
                onServerPathChange={(p) => updatePath('mask', p)}
                useDropzone={useDropzone['mask']}
                onToggleDropzone={(v) => toggleDropzone('mask', v)}
                isFolder={isFolderByType['mask']}
            />
        )}
        
        {/* Step 3: Upload CSVs */}
        {approach === 'stepByStep' && currentStep === 3 && (
            <StepUploadCSVs
                files={csvLabels} onAddFiles={addCSVLabels}
                includeCSV={includeCSV} onToggleInclude={setIncludeCSV}
                serverPath={pathsByType['csv']}
                onServerPathChange={(p) => updatePath('csv', p)}
                useDropzone={useDropzone['csv']}
                onToggleDropzone={(v) => toggleDropzone('csv', v)}
                isFolder={isFolderByType['csv']}
            />
        )}
        
        {/* Step 4: File List */}
        {approach === 'csvFileList' && currentStep === 4 && (
            <StepUploadFileList file={csvFile} onFile={setCsvFile} />
        )}
        
        {/* Step 5: Review */}
        {currentStep === 5 && (
            <StepReview
                approach={approach}
                reviewData={reviewData}
            />
        )}
        
        {/* Step 6: Complete */}
        {currentStep === 6 && <StepComplete />}
    </Modal.Body>
    <Modal.Footer>
        {currentStep > 0 && currentStep < 5 && (
            <Button variant="secondary" onClick={() => prevStep()}>Back</Button>
        )}
        {currentStep === 0 && <div />} {/* spacer, no back button */}
        {currentStep > 0 && currentStep < 5 && (
            <Button variant="primary" onClick={handleNext} disabled={!canProceed}>
                {nextButtonText}
            </Button>
        )}
        {currentStep === 5 && (
            <>
                <Button variant="primary" onClick={handleProcess} disabled={isProcessing || !canProcess}>
                    {isProcessing ? 'Processing...' : 'Process'}
                </Button>
                <Button variant="secondary" onClick={prevReviewStep}>Back</Button>
            </>
        )}
    </Modal.Footer>
</Modal>
```

**Step array determination (from `ps-upload.js`):**

```typescript
const steps = approach === 'csvFileList'
    ? ['Upload Method', 'Upload File List', 'Review Data']
    : ['Upload Method', 'Upload Scan Images', 'Upload Masks', 'Upload CSVs', 'Review Data']
```

**Review data state and validation flow:**

The modal maintains `reviewData` as local state (not a ref). When the user navigates to Step 5 (Review), the modal calls the `/validate/` endpoint:

```typescript
const [reviewData, setReviewData] = useState<ReviewRow[] | null>(null)

// Called when entering Step 5
const loadReviewData = async () => {
    let response
    if (approach === 'csvFileList') {
        // CSV approach: send the uploaded CSV file to the dedicated csv endpoint
        const formData = new FormData()
        formData.append('csv_file', csvFile.current!)
        response = await validateCsvProjectsProjectIdUploadSessionValidateCsvPost(projectId, session!, formData)
    } else if (Object.values(isFolderByType).some(Boolean)) {
        // "Load Folder" mode: send server folder paths
        response = await validateFoldersProjectsProjectIdUploadSessionValidateFoldersPost(projectId, session!, {
            image_folder: pathsByType.current['image'],
            mask_folder: pathsByType.current['mask'],
            patch_csv_folder: pathsByType.current['patch_csv'],
        })
    } else {
        // Drag-and-drop mode: send filenames from uploaded files
        response = await validatePathsProjectsProjectIdUploadSessionValidatePathsPost(projectId, session!, {
            paths: buildPathsFromRefs()
        })
    }
    setReviewData(response.paths)
}

// Called when user clicks "Process" on the review step
// Only sends ok rows, stripped of status/error fields
const handleProcess = async () => {
    setIsProcessing(true)
    const okRows = reviewData!.filter(r => r.status === 'ok')
    await processProjectsProjectIdUploadSessionProcessPost(projectId, session!, {
        paths: okRows.map(r => ({ image: r.image, mask: r.mask, csv: r.csv }))
    })
    toast.success('Upload processing started successfully')
    onClose()
}
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
3. Conditionally render `<UploadWizardModal projectId={projectId} onClose={() => setShowUploadWizard(false)} onSessionOpen={setSession} />` when `showUploadWizard` is true

---

## Backend Endpoints Needed

These endpoints do not exist yet. They are required for the Upload Wizard to function. The endpoint structure mirrors the old `ps-upload.js` API contract.

### Session Management

A Ray actor manages the upload session. The client calls `POST /api/v1/projects/{project_id}/upload/open/` to create the actor and receive the session UUID. All endpoints below accept it as a URL path segment.

### 0. `POST /api/v1/projects/{project_id}/upload/open/`

Create upload session (Ray actor). Returns a server-generated UUID.

**Response:**
```json
{
    "session": "uuid-string"
}
```

### 1. `POST /api/v1/projects/{project_id}/upload/{session}/images/`

Saves uploaded image files into the actor's temp directory. Calls the Ray actor's `save_images()` method.

**Request:**
```
Content-Type: multipart/form-data

files: [File, File, ...]
```

**Response:**
```json
{
    "message": "Uploaded 5 images"
}
```

### 2. `POST /api/v1/projects/{project_id}/upload/{session}/masks/`

Saves uploaded mask files into the actor's temp directory. Calls the Ray actor's `save_masks()` method. Same request/response as above.

### 3. `POST /api/v1/projects/{project_id}/upload/{session}/patch_csv/`

Saves uploaded patch CSV files into the actor's temp directory. Calls the Ray actor's `save_patch_csvs()` method. Same request/response as above.

### 4a. `POST /api/v1/projects/{project_id}/upload/{session}/validate/`

Unified validation endpoint for both file-drop and folder-based uploads. Accepts a combined request body with all path parameters. The endpoint attempts to match masks and/or patch_csv files to images, even when the upload type is mixed.

A row is **valid** (status: `ok`) if **either** a corresponding mask **or** a corresponding patch_csv is found. A row is **error** if **neither** is found.

**Request:**
```json
{
    "image_paths": ["img1.tif", "img2.tif"],
    "mask_paths": ["mask1.geojson", "mask2.geojson"],
    "patch_csv_paths": ["labels1.csv", "labels2.csv"],
    "image_folder": "/server/path/to/images/",
    "mask_folder": "/server/path/to/masks/",
    "patch_csv_folder": "/server/path/to/patch_csv/"
}
```

Only the relevant fields are populated depending on the upload mode:
- **File-drop mode**: `image_paths`, `mask_paths`, `patch_csv_paths` are populated
- **Folder mode**: `image_folder`, `mask_folder`, `patch_csv_folder` are populated
- **Mixed mode**: Both sets may be populated (user mixes folder and file-drop)

### 4b. `POST /api/v1/projects/{project_id}/upload/{session}/validate/patch_csv/`

Validates a patch CSV file list (CSV approach). Accepts `multipart/form-data`. Calls the Ray actor's `validate_patch_csv()` method. The CSV **must** include a header row `image,mask,patch_csv`.

**Request:**
```
Content-Type: multipart/form-data

csv_file: File
```

**All validate endpoints return the same response:**
```json
{
    "paths": [
        { "image": "/server/path/to/images/img1.tif", "mask": "/server/path/to/masks/mask1.geojson", "csv": "", "status": "ok", "error": "" },
        ...
    ],
    "errors": 0
}
```

### 4c. `POST /api/v1/projects/{project_id}/upload/{session}/validate/` (merged)

Merges the old `validate/paths/` and `validate/folders/` endpoints into a single unified endpoint. This allows mixed upload types (folder + file-drop) in a single validation call.

### 5. `POST /api/v1/projects/{project_id}/upload/{session}/process/`

Start server-side processing of validated paths. Accepts only `image`, `mask`, `csv` per row (no `status`/`error` fields).

**Request:**
```json
{
    "paths": [
        { "image": "img1.tif", "mask": "mask1.geojson", "csv": "" },
        { "image": "img2.tif", "mask": "", "csv": "labels2.csv" }
    ]
}
```

**Response:**
```json
{
    "task_id": "abc123",
    "status": "pending",
    "message": "Processing started"
}
```

---

## TypeScript Client Regeneration

After backend endpoints are implemented:

1. Run `npm run openapi-ts` in `patchsorter/client/`
2. New types: `OpenSessionResponse`, `UploadResponse`, `ValidateRequest`, `ValidateResponse`, `ProcessRequest`, `ProcessResponse`, `ReviewRow`
3. New SDK functions will be auto-generated from the OpenAPI spec — their names will match the operation IDs defined on each endpoint.

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

/* Review table container */
#upload-review-container {
    max-height: 400px;
    overflow-y: auto;
}

/* Approach descriptions */
.approach-description {
    padding: 16px;
    background: #f8f9fa;
    border-radius: 8px;
    margin-bottom: 16px;
}

/* Upload mode toggle ("Upload Files" / "Load Folder") */
.upload-mode-toggle {
    display: flex;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #dee2e6;
    margin-bottom: 16px;
    width: fit-content;
}
.upload-mode-toggle .toggle-option {
    padding: 6px 16px;
    cursor: pointer;
    background: #fff;
    border: none;
    color: #495057;
    font-size: 0.875rem;
    transition: background-color 0.15s, color 0.15s;
}
.upload-mode-toggle .toggle-option:not(:last-child) {
    border-right: 1px solid #dee2e6;
}
.upload-mode-toggle .toggle-option.active {
    background: #0d6efd;
    color: #fff;
}
.upload-mode-toggle .toggle-option:hover:not(.active) {
    background: #f8f9fa;
}
```

---

## Implementation Order

1. **Create `useUpload.ts`** — hook with state, refs, actions, and lazy `openSession()`
2. **Create `UploadStepIndicator.tsx`** — dynamic step progress bar (supports both step arrays)
3. **Create `StepApproachSelection.tsx`** — radio button step (step 0)
4. **Create `UploadWizardModal.tsx` (shell)** — renders step 0 and step indicator only; Next/Back wired; no upload step components yet
5. **Create `UploadWizardModal.css`** — all modal and component styles
6. **Wire up `ActionsFooter.tsx`** — add `onOpenUploadWizard` prop
7. **Wire up `ProjectPage`** — add `showUploadWizard` state, render modal
8. **Create `StepUploadImages.tsx`** — drag-drop + "Load Folder" toggle
9. **Create `StepUploadMasks.tsx`** — drag-drop + "Load Folder" toggle, `.geojson` only
10. **Create `StepUploadCSVs.tsx`** — drag-drop + "Load Folder" toggle
11. **Create `StepUploadFileList.tsx`** — CSV upload with header-row validation
12. **Create `StepReview.tsx`** — display-only review table
13. **Create `StepComplete.tsx`** — upload complete screen
14. **Expand `UploadWizardModal.tsx`** — integrate all step components, validation flow, Process handler
15. **Implement backend endpoints** (separate PR/phase)
16. **Regenerate TypeScript client** (after backend changes)
17. **Test all flows end-to-end**

---

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/client/src/components/projectPage/useUpload.ts` | **Create** — wizard state hook (useState + refs), session, toggles |
| `patchsorter/client/src/components/projectPage/UploadStepIndicator.tsx` | **Create** — step progress bar (global step → approach-specific label mapping) |
| `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx` | **Create** — radio button step (step 0) |
| `patchsorter/client/src/components/projectPage/StepUploadImages.tsx` | **Create** — image upload with Upload Files / Load Folder toggle |
| `patchsorter/client/src/components/projectPage/StepUploadMasks.tsx` | **Create** — GeoJSON mask upload with toggle |
| `patchsorter/client/src/components/projectPage/StepUploadCSVs.tsx` | **Create** — CSV upload with toggle |
| `patchsorter/client/src/components/projectPage/StepUploadFileList.tsx` | **Create** — CSV file list with header-row validation |
| `patchsorter/client/src/components/projectPage/StepReview.tsx` | **Create** — display-only review table (Image, Mask, CSV, Error, Status) |
| `patchsorter/client/src/components/projectPage/StepComplete.tsx` | **Create** — upload complete screen |
| `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx` | **Create** — modal shell (7-step wizard, lazy session, validate + process flow) |
| `patchsorter/client/src/components/projectPage/UploadWizardModal.css` | **Create** — modal styling including toggle buttons |

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
| `patchsorter/api/v1/upload/routes.py` | **Create** — upload endpoints (Ray actor-based), including unified `/validate/` endpoint |
| `patchsorter/api/v1/upload/models.py` | **Create** — upload request/response models (`ValidateRequest`, `ProcessRow`, etc.) |
| `patchsorter/api/v1/upload/actor.py` | **Create** — `UploadSessionActor` Ray actor class; stores `self._tmpdir`, exposes `cleanup()` |
| `patchsorter/api/v1/upload/gc_actor.py` | **Create** — `UploadSessionGarbageCollector` named Ray actor; periodic TTL-based cleanup of expired sessions |
| `patchsorter/api/v1/main.py` | Modify — include upload router, start GC actor at app init |
