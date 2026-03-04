# Design Document: Patch Sorter Interface

---

## 1. Landing Page

The Landing Page is the entry point of the application. It lists all existing projects and provides controls to create, edit, delete, and configure projects.

The page header displays **Projects (N)**, where N is the current project count, alongside a **Plus (+)** button to create a new project.

The projects table contains the following columns:

| Column | Description |
|---|---|
| **Project Name** | The name of the project |
| **Description** | A short description of the project |
| **DateTime** | Timestamp of when the project was created |
| **No. of images** | Number of images associated with the project |
| **Patch Size** | The configured patch size for the project |
| **No. of label classes** | Number of label classes defined in the project |
| **Action** | Per-row action buttons: Edit (blue pencil), Delete (red trash), Settings (gray gear) |

Clicking a project row navigates to that project's [Project Page](#project-page).

---

### 1.1 Create Project

Clicking the **Plus (+)** button in the page header opens the **New Project** dialog.

**Inputs:**

| Field | Type | Description |
|---|---|---|
| **Project Name** | Text input | Required. The name of the new project. |
| **Project Description** | Textarea | Required. A short description of the project. |
| **Patch Size** | Dropdown | Required. The patch size to use. Default: `256`. |

**Actions:**

| Action | Description |
|---|---|
| **Create Project** | Submits the form and creates the project. |

**States:**

| State | Description |
|---|---|
| *Default* | Empty form fields, **Create Project** button enabled. |
| *Saving* | A spinner and "Saving" label appear below the button while the request is in progress. |
| *Success* | Dialog closes and the new project appears in the projects table. |
| *Error* | An error message is displayed below the button. |

---

### 1.2 Edit Project

Clicking the **Edit** button (blue pencil icon) in a project row opens the project editing dialog.

**Inputs:**

| Field | Type | Description |
|---|---|---|
| **Project Name** | Text input | Pre-populated with the current project name. |
| **Project Description** | Textarea | Pre-populated with the current project description. |

**Actions:**

| Action | Description |
|---|---|
| **Save** | Submits the updated values. |
| **Cancel** | Closes the dialog without saving. |

**States:**

| State | Description |
|---|---|
| *Loading* | Spinner shown while the update request is in progress. |
| *Error* | An error message is displayed on failure. |

---

### 1.3 Delete Project

Clicking the **Delete** button (red trash icon) in a project row opens a confirmation dialog.

**Prompt:** "Are you sure you want to delete?"

**Actions:**

| Action | Description |
|---|---|
| **Confirm** | Permanently deletes the project. |
| **Cancel** | Closes the dialog without deleting. |

**States:**

| State | Description |
|---|---|
| *Loading* | Spinner shown while the deletion request is in progress. |
| *Error* | Displays **Error: error status** on failure. |

---

### 1.4 Project Settings

Clicking the **Settings** button (gray gear icon) in a project row opens the project settings dialog.

**Configurable Parameters:**

| Parameter | Type | Description |
|---|---|---|
| **Pad patches** | Boolean | Whether to pad patches. Default: `True`. |
| **Resize patches** | Boolean | Whether to resize patches. Default: `False`. |
| **Update embedding (s)** | Integer | Embedding update interval in seconds. Default: `5`. |

**Actions:**

| Action | Description |
|---|---|
| **Save** | Persists the updated settings. |
| **Reset** | Restores all settings to their default values. |

**Status Feedback:**

- **Settings saved!** — The project settings have been saved.
- **Settings reset!** — The project settings have been reset.

---

## 2. Project Page

The Project Page is the central hub for managing a single project. It displays project details, label classes, and images, and provides access to the labeling workflow.

The page header displays the **Project Name** and **Project Description**.

---

### 2.1 Manage Label Classes

The **Label Classes** section lists all defined label classes for the project and allows users to add, edit, and delete them.

**Label Classes Table:**

| Column | Description |
|---|---|
| **Name** | The label class name (e.g., "Nuclei") |
| **Comments** | Optional notes; displays "N/A" if empty |
| **DateTime** | Timestamp of creation or last modification |
| **No. GT labels** | Count of ground truth labels for this class |
| **Action** | Edit (blue pencil) and Delete (red trash) buttons |

**Add Label Class:**

A **Plus (+)** button next to the "Label Classes" header opens the creation dialog.

| Field | Type | Description |
|---|---|---|
| **Name** | Text input | Required. The name of the new label class. |
| **Color** | Color picker | Required. Display color for the class. |

| Action | Description |
|---|---|
| **Confirm** | Creates the new label class. |
| **Cancel** | Closes the dialog without saving. |

On failure: **Error: Failed to add new label class**

**Edit Label Class:**

Clicking the Edit button on a label class row opens the editing dialog with pre-populated fields.

| Field | Type | Description |
|---|---|---|
| **Name** | Text input | Current label class name. |
| **Color** | Color picker | Current label class color. |

On failure: **Error: Could not edit label class**

**Delete Label Class:**

Clicking the Delete button on a label class row opens a confirmation dialog equivalent to [Delete Project](#13-delete-project).

---

### 2.2 Upload Images

The **Images** section lists all images in the project. A **Plus (+)** button (pink/red icon) in the table header opens the **Upload Wizard**.

**Images Table:**

| Column | Description |
|---|---|
| **Thumbnail** | Small preview of the image |
| **Name** | File name (e.g., `image_file1.png`, `image_file2.svs`) |
| **Dimensions** | Resolution in pixels (e.g., `256×256`, `100,000×100,000`) |
| **No. Objects** | Count of annotated objects in the image |
| **Actions** | View/Edit (blue folder icon) and Delete (red trash icon) |

#### Upload Wizard

A 6-step wizard for uploading images and associated annotations.

A **step progress indicator** appears at the top of the wizard after selecting an approach, showing all 6 steps. The active step is highlighted; completed and future steps appear in gray.

---

##### Step 1: Approach

Users select an upload method:

| Option | Description |
|---|---|
| **Step by step** | Guided workflow through each upload type sequentially |
| **File list** | Upload all files at once via a CSV with columns: Image Filename, Mask Filename (optional), Label CSV Filename (optional) |

| Navigation | Description |
|---|---|
| **Next** | Proceed to Step 2 based on the selected approach |
| **Cancel** | Exit the wizard without saving |

---

##### Step 2: Upload Images

Users upload image files.

| Option | Description |
|---|---|
| **Upload Files** | Select individual image files |
| **Upload Folder** | Select an entire directory of images |

**Upload Box:**
- Header: "Upload Image Files (.svs, .png, etc.)"
- Drop zone: "Drop files or click to upload"
- Uploaded files are listed with a filename and a **Remove (×)** button

| Navigation | Description |
|---|---|
| **Back** | Return to Step 1 |
| **Next** | Proceed to Step 3 |
| **Cancel** | Exit the wizard |

---

##### Step 3: Upload Masks

Optional step for uploading mask files.

Users first choose whether to upload masks:

| Option | Description |
|---|---|
| **Yes** | Expand mask upload options |
| **No** | Skip to Step 4 |

If **Yes**, additional options appear:

| Field | Options |
|---|---|
| **Data source** | Upload Files, Upload Folder |
| **Mask type** | Geojson, Binary Mask, Multi-class Mask |

**Upload Box:**
- Header: "Upload Mask Files (.geojson, .json, .png)"
- Drop zone: "Drop files or click to upload"
- Uploaded files are listed with a filename and a **Remove (×)** button

| Navigation | Description |
|---|---|
| **Back** | Return to Step 2 |
| **Next** | Proceed to Step 4 |
| **Cancel** | Exit the wizard |

---

##### Step 4: Upload Labels

Optional step for uploading label CSV files.

Users first choose whether to upload label files:

| Option | Description |
|---|---|
| **Yes** | Expand label upload options |
| **No** | Skip to Step 5 |

If **Yes**, additional options appear:

| Field | Options |
|---|---|
| **Data source** | Upload Files, Upload Folder |

**Upload Box:**
- Header: "Upload .csv Files"
- Drop zone: "Drop files or click to upload"
- Uploaded files are listed with a filename and a **Remove (×)** button

> Uploaded label CSVs update the **No. Objects** count for the corresponding image.

| Navigation | Description |
|---|---|
| **Back** | Return to Step 3 |
| **Next** | Proceed to Step 5 |
| **Cancel** | Exit the wizard |

---

##### Step 5: Review

A summary table of all files queued for import is displayed before processing begins.

| Column | Description |
|---|---|
| **Image** | Image filename |
| **Mask** | Associated mask filename, or blank |
| **CSV** | Associated label CSV filename, or blank |
| **Error** | Validation error message, or "N/A" |
| **Status** | Current processing state (see below) |

**Status values:**

| Status | Description |
|---|---|
| **READY TO IMPORT** | File passed validation; ready to process |
| *(spinner)* | File is currently being processed |
| ✓ | File was successfully imported |
| ✗ | File import failed; see Error column |

**Validation checks include:**
- File naming consistency across images, masks, and CSVs
- Valid and supported file formats
- No conflicts with existing project data

| Navigation | Description |
|---|---|
| **Back** | Return to Step 4 |
| **Process** | Begin importing all queued files sequentially |
| **Cancel** | Exit the wizard without importing |

---

##### Step 6: Done

Confirms successful completion of the upload. The project dashboard updates to reflect newly added images.

---

### 2.3 Export Annotations

The **Export Labels** dialog allows users to export annotations from the project.

**Export Formats:**

| Format | Description |
|---|---|
| **GeoJSON files** | One `.geojson` file per image |
| **Image-level CSVs** | One `.csv` file per image |

**States:**

| State | Description |
|---|---|
| *Job running* | Export job has been submitted and is in progress |
| *File processing in progress* | Individual files are being written |

---

### 2.4 Open Labeling Page

A prominent **"Open Labeling Page"** button with an arrow icon appears at the bottom right of the Project Page.

- **Requirement:** At least 2 label classes must be defined. The button displays "Requires at least 2 label classes" and is disabled until this condition is met.
- **Action:** Navigates to the [Labeling Page](#3-labeling-page).

---

## 3. Labeling Page

The Labeling Page is the primary interface for annotating patches within a standard image. It is accessed via the **Open Labeling Page** button on the Project Page.

---

### 3.1 Select and Move Patches

Users can navigate and select patches using the available tools.

| Tool | Shortcut | Description |
|---|---|---|
| **Move** | `1` | Pan and navigate the image canvas |
| **Lasso** | `2` | Draw a freeform selection region to select multiple patches |

**Bulk selection:** The **Select all patches** option selects all visible patches at once.

---

### 3.2 Assign Labels

Once patches are selected, labels are assigned via the **Apply Label** menu.

- Available label classes are listed with numeric shortcuts, e.g., **(1) Epithelial cell**, **(2) Lymphocyte**, **(3) Other**.
- The current default label assignment is shown in the interface, e.g., "'ENTER' assigns label: **Lymphocyte**".
- Pressing `ENTER` assigns the currently configured default label to the selected patches.

---

### 3.3 Visualization and Filtering

Users can control the display of patches and labels using the following options:

| Option | Description |
|---|---|
| **Color By Ground Truth** | Colors patches by their assigned ground truth label |
| **Filter By Labeled** | Shows only patches that have been labeled |
| **Include Label Classes** | Filters the view to include specific label classes (e.g., Lymphocyte) |
| **Toggle Show Patches** | Toggles visibility of patch overlays on the image |

---

### 3.4 Navigate to Embedding View

A navigation control allows users to switch to the **Embedding** view, which provides a dimensionality-reduced visualization of patch features to assist with batch labeling decisions.

---

## 4. WSI Labeling Page

The WSI (Whole Slide Image) Labeling Page provides an annotation interface optimized for very large images (e.g., `.svs` files with resolutions up to `100,000×100,000` pixels). It is accessed by clicking the **View/Edit** button on a whole slide image in the Project Page images table.
