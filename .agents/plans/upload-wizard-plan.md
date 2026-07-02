# Upload Wizard – Implementation Plan

## Overview

Add a multi-step Upload Wizard as a Bootstrap `<Modal>` on the Project Page. The wizard supports two upload approaches:

1. **Step-by-Step** — Upload images, masks, and CSV labels in separate steps, then review.
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
   refs (useUpload hook):
     approach: 'stepByStep' | 'csvFileList' | null
     currentStep: number (0–6)
     session: string | null           // set by open upload session endpoint
     images: File[]
     masks: File[]
     csvLabels: File[]
     csvFile: File | null
     useDropzone: Record<uploadType, boolean>  // per-type toggle
     includeMasks: boolean
     includeCSV: boolean
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
2. Modal calls `POST /api/v1/projects/{project_id}/upload/{session}/validate/` with file paths from refs
3. Server returns `ReviewRow[]` with status per row
4. Modal stores results in local state (`reviewData`)
5. `<StepReview>` renders the table from `reviewData`

### Upload Types (from `ps-upload.js`)

| Type | Accepts | Purpose |
|------|---------|---------|
| `image` | `image/*` | Scan images (WSI tiles) |
| `mask` | `image/*` | Mask images (binary/grayscale) |
| `csv` | `.csv` | Label CSV files |

### Per-Type Toggle: "Upload Files" vs "Load Folder"

Each upload step (images, masks, CSVs) has a toggle between two modes:

- **Upload Files** — Client-side drag-drop zone (dropzone) for local files
- **Load Folder** — Text input for server-side directory paths (remote files)

This is a critical feature from the old wizard that is **missing** from the original plan. The toggle controls which UI is shown per upload type.

### Optional Inputs

Masks and CSV uploads are optional. Each has a toggle (`includeMasks`, `includeCSV`) that hides/shows the upload step entirely.

### Session Management via Ray Actor

The upload session is managed by a **Ray actor** that:
- Uses Python's `tempfile.TemporaryDirectory` to create a temp directory for the session
- The temp directory lives for the lifetime of the actor and is deleted when the actor dies
- Session UUID is **server-side generated** (not client-side)

The client calls `POST /api/v1/projects/{project_id}/upload/open/` to create the actor and receive the session UUID. All subsequent endpoints use this session ID as a URL path segment.

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
      StepUploadCSVs.tsx           ← Step 3: drag-drop or server path for CSV labels
      StepUploadFileList.tsx       ← Step 4: CSV file list upload
      StepReview.tsx               ← Step 5: unified review table
      StepComplete.tsx             ← Step 6: upload complete screen
      useUpload.ts                 ← Wizard state management hook with refs
```

---

## Step 0: Create `useUpload.ts` Hook

**File:** `patchsorter/client/src/components/projectPage/useUpload.ts`

A custom hook returning refs (not state) so that child components can mutate file lists without causing re-renders, and the Review step can read live values.

```typescript
interface UploadWizardState {
    // Core state
    approach: React.MutableRefObject<'stepByStep' | 'csvFileList' | null>
    currentStep: React.MutableRefObject<number>  // 0–6
    session: string | null                        // set by open upload session endpoint
    
    // File refs
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    csvLabels: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>
    
    // Server paths (for "Load Folder" mode)
    pathsByType: React.MutableRefObject<Record<string, string>>
    isFolderByType: React.MutableRefObject<Record<string, boolean>>
    
    // Toggles
    includeMasks: React.MutableRefObject<boolean>
    includeCSV: React.MutableRefObject<boolean>
    useDropzone: React.MutableRefObject<Record<string, boolean>>
    
    // Actions
    openSession: () => Promise<void>
    setApproach: (a: 'stepByStep' | 'csvFileList') => void
    nextStep: () => void
    prevStep: (targetStep?: number) => void
    addImages: (files: File[]) => void
    addMasks: (files: File[]) => void
    addCSVLabels: (files: File[]) => void
    setCsvFile: (file: File | null) => void
    reset: () => void
}
```

**Key behaviors:**
- `openSession()` calls `POST /api/v1/projects/{project_id}/upload/open/` to create the Ray actor and stores the returned session ID
- `reset()` clears all refs and sets `currentStep` to 0
- `nextStep()` advances `currentStep`, auto-skipping empty optional steps (masks/CSVs)
- `prevStep(targetStep?)` goes back one step or jumps to a specific step
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

**Step arrays (from `ps-upload.js`):**

| Approach | Steps (7 total) |
|----------|-----------------|
| Step-by-Step | `['Upload Method', 'Upload Scan Images', 'Upload Masks', 'Upload CSVs', 'Review Data', 'Upload Complete']` |
| CSV File List | `['Upload Method', 'Upload File List', 'Review Data', 'Upload Complete']` |

Note: The old wizard uses 7 steps (0–6) with the following mapping:
- Step 0: Upload Method (approach selection)
- Step 1: Upload Scan Images
- Step 2: Upload Masks
- Step 3: Upload CSVs
- Step 4: File List (CSV approach)
- Step 5: Review Data
- Step 6: Upload Complete

---

## Step 2: Create `StepApproachSelection.tsx`

**File:** `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx`

Step 0: two radio button options.

**Options:**
1. **Step-by-step** — "Upload images, masks, and labels individually"
2. **File List** — "Upload a CSV with 3 columns: image filename, mask filename, csv filename (absolute paths on the server)"

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

Same as `StepUploadImages` but for mask files (GeoJSON format only).
- **Optional toggle**: "Upload Masks" can be disabled entirely (hides the step)

### `StepUploadCSVs.tsx`

Same as `StepUploadImages` but for CSV label files.
- **Optional toggle**: "Upload CSVs" can be disabled entirely (hides the step)

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
- **Validates 3-column format**: image filename, mask filename, csv filename (no header row)
- Shows validation errors if format is incorrect
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
    isProcessing: boolean
    onProcess: () => void
    onBack: () => void
}
```

### Review table columns (from `ps-upload.js` `makeResultsRow`)

| Column | Field | Formatter |
|--------|-------|-----------|
| Image | `image` | Text |
| Mask | `mask` | Text |
| CSV | `csv` | Text |
| Error | `error` | Red text if present |
| Status | `status` | Green "ok" or red "error" |

### Dataset building

```typescript
// reviewData comes directly from the /validate/ endpoint response
// Each row has: image, mask, csv, error, status fields
const dataset = useMemo(() => reviewData ?? [], [reviewData])
```

### Upload button

A "Process" button below the grid that triggers the `/process/` API call. Shows a spinner while processing. If errors exist or no valid rows, the button is disabled with an error message.

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

**On mount:** call `openSession()` to create the Ray actor and populate `session`.

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
                isProcessing={isProcessing}
                onProcess={handleProcess}
                onBack={goBackFromReview}
            />
        )}
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
                <Button variant="secondary" onClick={() => prevStep(4)}>Back</Button>
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
    let payload: ValidateRequest
    if (approach === 'csvFileList') {
        // Read CSV file content from file ref
        const csvContent = await readFile(csvFile.current!)
        payload = { csv_content: csvContent }
    } else {
        // Build from server paths or uploaded file names
        payload = { paths: buildPathsFromRefs() }
    }
    const response = await validateProjectsProjectIdUploadSessionValidatePost(projectId, session!, payload)
    setReviewData(response.paths)
}

// Called when user clicks "Process" on the review step
const handleProcess = async () => {
    setIsProcessing(true)
    await processProjectsProjectIdUploadSessionProcessPost(projectId, session!, { paths: reviewData! })
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

### 3. `POST /api/v1/projects/{project_id}/upload/{session}/labels/`

Saves uploaded label files into the actor's temp directory. Calls the Ray actor's `save_labels()` method. Same request/response as above.

### 4. `POST /api/v1/projects/{project_id}/upload/{session}/validate/`

Validates file paths. Calls the Ray actor's `validate()` method. Accepts **any one** of the following input types (exactly one must be provided):

**(A) Client-side paths from drag-and-drop uploads:**
```json
{
    "paths": [
        { "type": "image", "filename": "img1.tif" },
        { "type": "mask", "filename": "mask1.geojson" },
        ...
    ]
}
```

**(B) Server folder paths (for "Load Folder" mode):**
```json
{
    "image_folder": "/server/path/to/images/",
    "mask_folder": "/server/path/to/masks/",
    "label_folder": "/server/path/to/labels/"
}
```

**(C) CSV file with 3 columns (image, mask, label filenames):**
```
Content-Type: multipart/form-data

csv_file: File
```

**Response:**
```json
{
    "paths": [
        { "image": "/server/path/to/images/img1.tif", "mask": "/server/path/to/masks/mask1.geojson", "label": "", "status": "ok", "error": "" },
        ...
    ],
    "errors": 0
}
```

### 5. `POST /api/v1/projects/{project_id}/upload/{session}/process/`

Start server-side processing of validated paths. Calls the Ray actor's `process()` method, which dispatches Ray tasks.

**Request:**
```json
{
    "paths": [...]  // from validate response
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
3. New SDK functions: `openSessionProjectsProjectIdUploadOpenPost`, `uploadImagesProjectsProjectIdUploadSessionImagesPost`, `uploadMasksProjectsProjectIdUploadSessionMasksPost`, `uploadLabelsProjectsProjectIdUploadSessionLabelsPost`, `validateProjectsProjectIdUploadSessionValidatePost`, `processProjectsProjectIdUploadSessionProcessPost`

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
```

---

## Implementation Order

1. **Create `useUpload.ts`** — hook with refs, actions, and `openSession()`
2. **Create `UploadStepIndicator.tsx`** — dynamic step progress bar (supports both step arrays)
3. **Create `StepApproachSelection.tsx`** — radio button step (step 0)
4. **Create `StepUploadImages.tsx`** — drag-drop + "Load Folder" toggle
5. **Create `StepUploadMasks.tsx`** — drag-drop + "Load Folder" toggle
6. **Create `StepUploadCSVs.tsx`** — drag-drop + "Load Folder" toggle
7. **Create `StepUploadFileList.tsx`** — CSV upload with 3-column validation
8. **Create `StepReview.tsx`** — review table (displays `/validate/` results)
9. **Create `UploadWizardModal.tsx`** — modal shell orchestrating all steps (closes on Process, shows toast)
10. **Create `UploadWizardModal.css`** — modal and component styles
11. **Wire up `ActionsFooter.tsx`** — add `onOpenUploadWizard` prop
13. **Wire up `ProjectPage`** — add `showUploadWizard` state, render modal
14. **Implement backend endpoints** (separate PR/phase)
15. **Regenerate TypeScript client** (after backend changes)
16. **Test all flows end-to-end**

---

## Files to Create

| File | Action |
|------|--------|
| `patchsorter/client/src/components/projectPage/useUpload.ts` | **Create** — wizard state hook with refs, session, toggles |
| `patchsorter/client/src/components/projectPage/UploadStepIndicator.tsx` | **Create** — step progress bar (7-step aware) |
| `patchsorter/client/src/components/projectPage/StepApproachSelection.tsx` | **Create** — radio button step (step 0) |
| `patchsorter/client/src/components/projectPage/StepUploadImages.tsx` | **Create** — image upload with Upload Files / Load Folder toggle |
| `patchsorter/client/src/components/projectPage/StepUploadMasks.tsx` | **Create** — mask upload with toggle |
| `patchsorter/client/src/components/projectPage/StepUploadCSVs.tsx` | **Create** — CSV upload with toggle |
| `patchsorter/client/src/components/projectPage/StepUploadFileList.tsx` | **Create** — CSV file list with 3-column validation |
| `patchsorter/client/src/components/projectPage/StepReview.tsx` | **Create** — review table (Image, Mask, CSV, Error, Status) |
| `patchsorter/client/src/components/projectPage/UploadWizardModal.tsx` | **Create** — modal shell (closes on Process, shows toast) |
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
| `patchsorter/api/v1/upload/routes.py` | **Create** — upload endpoints (Ray actor-based) |
| `patchsorter/api/v1/upload/models.py` | **Create** — upload request/response models |
| `patchsorter/api/v1/upload/actor.py` | **Create** — Ray actor class for upload session management |
| `patchsorter/api/v1/main.py` | Modify — include upload router |
