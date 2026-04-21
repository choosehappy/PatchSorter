# Design Document: Patch Sorter Interface

---

## 1. Landing Page

The Landing Page is the entry point of the application. It lists all existing projects and provides controls to create, edit, delete, and configure projects.

The page header displays **Projects (N)**, where N is the current project count, alongside a **Plus (+)** button to create a new project. Access buttons for **Application Settings** and **Project Settings** are also available in the header.

### Projects Table

The projects table contains the following columns:

| Column | Description |
|---|---|
| **Project Name** | The name of the project |
| **Description** | A short description of the project |
| **Creation Date** | Timestamp of when the project was created |
| **Modification Date** | Timestamp of last modification |
| **No. of images** | Number of images associated with the project |
| **Patch Size** | The configured patch size for the project (e.g., 256) |
| **No. of label classes** | Number of label classes defined in the project |
| **No. Total Objects** | Total number of objects in the project |
| **No. Labeled** | Number of labeled objects |
| **Action** | Per-row action buttons: Edit, Delete, Settings (via gear icon) |

Clicking a project row navigates to that project's [Project Page](#project-page).

---

### 1.1 Create Project

Clicking the **Plus (+)** button in the page header opens the **New Project** dialog.

**Inputs:**

| Field | Type | Description |
|---|---|---|
| **Project Name** | Text input | Required. The name of the new project. |
| **Project Description** | Textarea | Required. A short description of the project. |
| **Patch Size** | Dropdown/Number input | Required. The patch size to use. Default: `256`. |

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

## 2. Project Page

The Project Page displays detailed information and controls for managing a specific project. It includes tabs or sections for **Application Settings**, **Project Settings**, and project-specific actions.

### 2.1 Header Bar

The header displays:
- **Projects (N)** counter
- **Application Settings** button
- **Project Settings** button

---

### 2.2 Project Settings Section

This section allows modification of core project parameters.

**Settings Table:**

| Setting Name | Value | Actions |
|---|---|---|
| Pad patches | [Toggle/Value] | Save, Reset |
| Resize patches | [Toggle/Value] | Save, Reset |
| Update embedding(s) | [Toggle/Value] | Save, Reset |

**Actions:**
- **Save** (`[💾]` icon): Saves the current settings configuration. Displays "Settings saved!" toast notification on success.
- **Reset**: Resets all project settings to defaults. Displays "Settings reset!" toast notification on success.

**Pad Patches Setting:**
- Controls padding around patches during extraction.
- Default: 0 pixels (or adjustable via slider/input).

**Resize Patches Setting:**
- Allows resizing of extracted patches.
- Options include standard resize methods (e.g., nearest neighbor, bilinear interpolation).

**Update Embedding(s) Setting:**
- Toggle to enable/disable embedding updates for the project.
- Default value: 5 (number of embedding dimensions or iterations).

---

## 3. Import/Upload Section

This section handles the initial data ingestion for projects.

### 3.1 Upload Methods

Three upload options are available:

| Method | Description | Recommended Use Case |
|---|---|---|
| **Upload Files** | Individual file selection via drag-and-drop or file picker | < 100 images |
| **Upload Folder** | Batch upload of entire directory | > 100 images (recommended) |
| **File List** | Upload a TSV/CSV file listing image paths | Large datasets with predefined paths |

**Supported Image Formats:**
- `.png`, `.svs`, `.geoson`, `.cov`, and other common image formats.

**Upload State Indicators:**
- Progress counters showing number of uploaded images.
- Error indicators for failed uploads.

### 3.2 Label Upload

**Label File Upload:**
- **CSV Files**: Required format for label data.
- If no labels are uploaded, objects are considered "unlabeled".

**Mask Format Selection:**
- Dropdown to specify mask file format (e.g., `.tif`, `.png`).
- Used when uploading segmented masks alongside images.

**Upload Dialog Options:**
- **Open Labeling Page**: Button to proceed directly to annotation interface after upload.
- **Export All Patch Labels**: Button to export labels after processing.

---

## 4. Image List Management (Labeling Configuration Page)

This page manages the list of images and their associated label classes.

### 4.1 Image List Table

The table displays the following columns:

| Column | Description |
|---|---|
| **Thumbnail** | Small preview image of the content |
| **Name** | Image file name |
| **Width** | Image width in pixels |
| **Height** | Image height in pixels |
| **No. Total** | Total number of objects/patches |
| **No. Unlabeled** | Count of unlabeled objects |
| **Label Class 1** | Checkbox/indicator for Class 1 assignment |
| **Label Class 2** | Checkbox/indicator for Class 2 assignment |
| **Actions** | Per-row action buttons: Open Labeling Page, Color (for mask visualization), Export All Image Labels |

### 4.2 Label Class Management

**Add New Label Class:**
- Button to create a new label class category.
- Requires input of the new class name.
- Displayed in dropdown/input field above table.

**Label Class Editing:**
- Each row can edit existing label classes.
- Input fields for: "New label class name", "Class 1", "Class 2", etc.

**States:**

| State | Description |
|---|---|
| *Default* | Empty state with "Add a new label class" option. |
| *Loading* | Shows loading spinner during data fetch or save operations. |
| *Saving* | Button shows "Saving Label Class..." during update operation. |
| *Success* | Changes applied, table refreshes automatically. |
| *Error: Failed to add new label class* | Displayed when class name is invalid or duplicate. |
| *Error: Could not edit label class* | Displayed when editing fails due to data corruption or permissions. |

**Actions per Row:**

| Action | Icon/Button | Description |
|---|---|---|
| Open Labeling Page | `[▶]` (Play/Forward) | Navigate to annotation interface for this image. |
| Color | `[●]` | Toggle color visualization of masks/labels. |
| Export All Image Labels | Button | Exports all labels for this image in batch. |
| Cancel | Button | Cancels current operation (e.g., editing). |

---

## 5. Labeling Interface (Annotation View)

The Labeling Page is where users annotate patches and assign label classes.

### 5.1 Toolbar & Controls

**Top Toolbar:**
- **Next/Previous**: Navigate between images or patches (`Cv e— Ev se—` buttons).
- **Cancel**: Aborts current annotation session.

**Side/Sidebar Controls:**
- **Zoom**: Zoom in/out of the image view.
- **Pan**: Drag to navigate within the image.
- **Scroll**: Scroll through content if larger than viewport.
- **Annotation Tools**: Brush, eraser, selector tools for drawing patches.
- **Brush Size Slider**: Adjust size of annotation brush.
- **Color Picker**: Select color for label overlays/masks.
- **Label Class Selector**: Dropdown to choose active label class from available classes (Class 1, Class 2, etc.).

### 5.2 Image/Patch View

The main area displays:
- Full or zoomed view of the image/patch.
- Overlay grid showing patch extraction regions.
- Color-coded mask overlays for labeled patches.
- Annotation marks and bounding boxes drawn by users.

**View Modes:**
- **Single Patch**: Focus on one extracted patch at a time.
- **Grid View**: Display multiple patches in a tiled layout.
- **Full Image**: View entire image with overlay annotations.

### 5.3 Patch Extraction Controls

Accessed via settings or dedicated panel:

| Control | Options | Description |
|---|---|---|
| **Downsample Factor** | Integer input (e.g., 1:2) | Reduces image resolution for faster processing. 1:2 = half resolution. |
| **Patch Extraction Method** | Dropdown | Choose between: <br> • *Center crop and resize*: One patch per object <br> • *Stride*: Multiple patches per object/annotation |

---

## 6. Label Classes Management (List View)

A dedicated view to manage all label classes across the project.

### 6.1 Table Structure

Columns:
- **Name**: Class name (e.g., "unknown", "irrelevant")
- **Comments**: Optional notes for each class
- **Creation Date**: Timestamp when class was added
- **Modification Date**: Last edit timestamp
- **No. GT labels**: Count of ground truth labels assigned to this class
- **Action**: Edit/Delete buttons per class

### 6.2 Add Label Class Dialog

**Inputs:**
- **Name**: Required text input for the new class name.
- **Comments**: Optional textarea for class description.

**Actions:**
- **Add**: Creates the new label class.
- **Cancel**: Discards changes.

---

## 7. Export Functions

### 7.1 Export All Patch Labels

**Location:** Found on labeling configuration page and project actions.

**Functionality:**
- Exports all annotated patches for the project or selected images.
- Output format: Typically TSV or CSV with columns: patch_path, label_class, coordinates, metadata.
- Triggered via dedicated button: `Export All Patch Labels [▶]`.

### 7.2 Export All Image Labels

**Location:** Image list management page per row.

**Functionality:**
- Exports labels for a specific image or batch of images.
- Includes image metadata (width, height, name) alongside labels.
- Format: CSV with structured columns per label type.

---

## 8. Filter & Search Controls

### 8.1 Toolbar Filters

Available filter options include:
- **Label Classes**: Checkbox filters to show/hide patches by assigned class.
- **Mask Types**: Toggle between different mask visualizations (e.g., segmented vs. raw).
- **Search Bar**: Text input to search image names or labels.

### 8.2 Legend Control

**Button:** `msc teamna` / `mace legen` / `mse fie sce Wa` (likely internal component names)
- Displays/hides legend overlay showing color codes for each label class.
- Shows mapping between colors and label categories.

---

## 9. Toast Notifications & Feedback

The application uses non-intrusive toast notifications for user feedback:

| Notification | Trigger | Message |
|---|---|---|
| **Settings saved!** | Click Save button | Confirmation that project settings were persisted. |
| **Settings reset!** | Click Reset button | Confirmation that settings reverted to defaults. |
| **Saving Label Class...** | Edit operation in progress | Indicates asynchronous save is occurring. |
| **Error: Failed to add new label class** | Invalid input during class creation | Describes the validation failure. |
| **Error: Could not edit label class** | Save failed due to data issues | Generic error for editing failures. |

---

## 10. Base Magnification Setting

A setting in the labeling interface controls:

**"What is the base magnification of your images?"**
- Allows users to define the native zoom level or optical magnification for microscopy/medical imaging datasets.
- Used for accurate scaling and annotation when working with high-magnification images.
- Options likely include: 10x, 20x, 40x, 60x, 100x, etc. (microscope standard objectives).

---

## Summary of Key Features

1. **Project Management**: Create, edit, delete projects with configurable patch sizes and object counts.
2. **Flexible Import**: Support for individual files, folder uploads, or file list TSVs.
3. **Configurable Patch Extraction**: Choose between center-crop (1 patch per object) or stride (multiple patches).
4. **Downsampling Control**: Adjustable resolution reduction for performance optimization.
5. **Rich Label Class System**: Multi-class annotation with color-coded masks and editable categories.
6. **Interactive Annotation Interface**: Zoom, pan, scroll, brush tools, and label selection for precise labeling.
7. **Batch Export Options**: Export patch labels or image-level labels in structured formats.
8. **Visual Feedback**: Toast notifications for save/reset actions and error handling.

---
