# Design Document: Patch Sorter Interface

---

## 1. Landing Page.

The Landing Page is the entry point of the application. It lists all existing projects and provides controls to create, edit, delete, and configure projects.

### Use Case: Create Project
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase1_create_project.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Delete Project
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase2_delete_project.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

The page header displays **Projects (N)**, where N is the current project count, alongside a **Plus (+)** button to create a new project.

The projects table contains the following columns (as shown in the UI):

| Column | Description |
|---|---|
| **Project Name** | The name of the project |
| **Description** | A short description of the project |
| **Creation Date** | Timestamp of when the project was created |
| **Modification Date** | Timestamp of last modification |
| **No. of images** | Number of images associated with the project |
| **Patch Size** | The configured patch size for the project |
| **No. of label classes** | Number of label classes defined in the project |
| **No. Total Objects** | Total number of objects in the project |
| **No. Labeled** | Number of labeled objects |
| **Action** | Per-row action buttons: Edit (blue pencil), Delete (red trash), Settings (gray gear) |

Clicking a project row navigates to that project's [Project Page](#project-page).

---

### 1.1. Create Project

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

## 2. Project Page.

The Project Page is accessed by clicking a project row from the Landing Page. It displays project metadata, label classes, and image thumbnails with labeling controls.

### Use Case: Add Label Classes
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase3_add_label_classes.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Edit Label Classes
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase4_edit_label_classes.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Enter Project Page
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase5_enter_project_page.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Upload, Step-by-step
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase6_upload_step_by_step.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Upload, File list
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase7_upload_file_list.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Check Job Status
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase8_check_job_status.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Export Annotations With Labels
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase16_export_annotations_with_labels.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

The page header displays the project title and a breadcrumb: **Projects > [Project Name]**. It includes a **Back** button to return to the Landing Page and a **Settings** (gear) button to open project settings.

Below the header, the page is divided into three sections:

### 2.1. Project Metadata

Displays project-level information:

| Field | Description |
|---|---|
| **Project Title** | The project name |
| **Description** | The project description |
| **Creation Date** | Timestamp of project creation |
| **Modification Date** | Timestamp of last modification |
| **No. of images** | Total number of images |
| **Patch Size** | Configured patch size |
| **No. of label classes** | Number of defined label classes |
| **No. Total Objects** | Total objects across all images |
| **No. Labeled** | Number of labeled objects |

### 2.2. Label Classes

Displays all label classes in a collapsible list. Each class can be edited or deleted.

**Actions:**

| Action | Description |
|---|---|
| **Edit Label Class** | Opens an inline editor for the label class. |
| **Delete Label Class** | Confirms deletion of the label class. |
| **New Label Class** | Opens a modal to add a new label class. |

**Label Class Modal Inputs:**

| Field | Type | Description |
|---|---|---|
| **Name** | Text input | Required. The name of the label class. |
| **Color** | Color picker | Optional. Assigns a visual color to the label. |
| **Comments** | Textarea | Optional. Additional notes. |

**States:**

| State | Description |
|---|---|
| *Default* | Empty modal with "Add New Label Class" button. |
| *Saving* | Spinner and "Saving" label while processing. |
| *Success* | Label class added to list, modal closes. |
| *Error* | Error message displayed if validation fails. |

### 2.3. Images

Displays a grid of image thumbnails. Each thumbnail has:

- **Actions**: Open Labeling Page (blue button), Export Labels (green button)
- **Metadata**: Image name, width, height, total objects, unlabeled objects, per-class counts

**Actions per Image:**

| Action | Description |
|---|---|
| **Open Labeling Page** | Opens the labeling interface for this image. |
| **Export All Image Labels** | Exports all labels for this image as a JSON file. |

**States:**

| State | Description |
|---|---|
| *Default* | Images displayed with metadata and action buttons. |
| *Loading* | Spinner while fetching or processing image data. |
| *Error* | Error message if image fails to load or export. |

---

## 3. Labeling Interface.

Accessed via **Open Labeling Page** from the Images section.

### Use Case: Enter Object Labeling Page
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase9_Enter_object_labeling_page.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Enter Image View
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase10_Enter_image_view.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Show Patches
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase11_show_patches.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Navigate Embedding
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase12_Navigate_embedding.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Assign Labels
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase13_assign_labels.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Filter Embedding
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase14_filter_embedding.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### Use Case: Enter Image View From Patch
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase15_enter_image_view_from_patch.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### 3.1. Overview

Displays a single image with a grid of patches (based on configured patch size). Each patch has:

- **Label selector**: Dropdown to choose a label class (default: "Unlabeled")
- **Confidence slider**: Optional for labeling confidence (0–100%)
- **Save button**: Saves label for the patch

### 3.2. Controls

| Control | Description |
|---|---|
| **Previous/Next** | Navigate between images. |
| **Save Labels** | Saves all labels for the current image. |
| **Export Labels** | Exports all labels as JSON. |
| **Reset Labels** | Clears all labels for the current image. |

### 3.3. States

| State | Description |
|---|---|
| *Default* | Image loaded, patches displayed, label selector active. |
| *Saving* | Spinner and "Saving" label during save. |
| *Success* | Confirmation toast appears after successful save. |
| *Error* | Error message if save fails. |

---

## 4. Settings Page.

Accessed via the gear icon in the project header.

### Use Case: Enter Settings
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase17_enter_settings.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

### 4.1. Settings

| Setting | Description |
|---|---|
| **Patch Size** | Dropdown to change patch size (256, 512, 1024). |
| **Default Label Class** | Dropdown to set default label class for new labels. |
| **Auto-save** | Toggle to enable/disable auto-saving labels. |
| **Export Format** | Dropdown for export format: JSON, CSV, TFRecord. |

### 4.2. Actions

| Action | Description |
|---|---|
| **Save Settings** | Saves changes and applies them to the project. |
| **Reset Settings** | Resets settings to default values. |

### 4.3. States

| State | Description |
|---|---|
| *Default* | All settings displayed with "Save Settings" button. |
| *Saving* | Spinner and "Saving" label while processing. |
| *Success* | Confirmation toast appears after saving. |
| *Error* | Error message if saving fails. |

---

## 5. Export Functionality.

### 5.1. Export All Image Labels

Located in the Images section. Exports all labeled objects for the project.

**Actions:**

| Action | Description |
|---|---|
| **Export** | Triggers export. |
| **Cancel** | Cancels export if in progress. |

**States:**

| State | Description |
|---|---|
| *Default* | "Export All Image Labels" button visible. |
| *Processing* | Spinner and "Exporting…" label while processing. |
| *Success* | File download starts, toast confirms success. |
| *Error* | Error message if export fails. |

---

## 6. Error Handling.

### Use Case: Control DL Processing
<div style="overflow-x: auto; width: 100%;">
  <img src="../_static/figma_mockups/Usecase18_control_DL_processing.png" style="height: 400px; width: auto; max-width: none; display: block;">
</div>

All components display error states with:

- Toast notifications (for transient errors)
- Inline error messages (for form validation)
- Modal error messages (for critical actions like deletion or export)

**Error Types:**

| Type | Description |
|---|---|
| *Validation* | Form fields not meeting required criteria. |
| *Network* | Failed API calls (e.g., save, export, delete). |
| *User Action* | Confirmed user actions (e.g., deletion) failed. |

---

## 7. UI States.

### 7.1. Loading States

- Spinners in buttons or modals during async operations.
- "Loading…" text overlays during data fetches.

### 7.2. Success States

- Toast notifications with success messages.
- "Success" labels on buttons after completion.

### 7.3. Error States

- Toast or modal with error message.
- "Error" label on buttons or inputs.
- Red outlines on failed form fields.

---

## 8. Navigation.

### 8.1. Breadcrumbs

- **Projects > [Project Name]** on Project Page.
- **Landing Page** accessible via "Back" button.

### 8.2. Routing

- Clicking project row → navigates to Project Page.
- Clicking "Back" → returns to Landing Page.
- Clicking "Settings" → opens Settings modal.

---

## 9. Accessibility.

- All buttons and inputs are keyboard-navigable.
- Labels and tooltips are descriptive.
- High contrast mode supported for visual impairments.


--- 

*Document generated from Figma mockups (Sections 1–21).*
---
