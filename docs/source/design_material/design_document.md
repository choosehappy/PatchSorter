# Design Document: Patch Sorter Interface

## 1. Project Management & Overview

### 1.1. Projects Landing Page

The main landing page lists existing projects in a tabular format.
- Each project has the following properties displayed
  - **Project Name**
  - **Description**
  - **Date Created**
  - **Number of Images**
  - **Number of Patches**
  - **Number of Label Classes**
- Action buttons are available for each project:
  -  **Edit Project**
  -  **Delete Project**
-  Clicking on a project row navigates to the Project Page.

### 1.2. Project Creation

Project configuration is handled under the `New Project` interface. Click the **Plus** button next to the `Projects` header to open this interface.

*   **Required Inputs:** Users must configure the **Project Name** (Value) and **Project Description** (Value). A **Help** element is also present.
*   **Actions and Status:** The creation process is initiated by the **Create Project** button. A **Loading** state is shown while the project is being created.

### 1.3. Project Deletion

Deletion is confirmed via a dedicated dialog.

*   **Interface:** The `Delete Project` dialog prompts the user with the question: "**Are you sure you want to delete?**".
*   **Actions and Status:** Actions include **Confirm** and **Cancel**. Status indicators show **Loading** during the deletion process or display an **Error: error status** upon failure.

---

## 2. Project Dashboard

The Project Dashboard serves as the central hub for managing a single project. It provides an overview of project details, label classes, and images, with direct access to labeling workflows.

### 2.1. Project Details Display

At the top of the dashboard:
*   **Name:** Displays the project name (e.g., `Project Title` or `Project 1`)
*   **Description:** Shows the project description (e.g., `Project description displayed here.`)

### 2.2. Label Class Management

The **Label Classes** section manages the types of objects that can be labeled within the project.

#### 2.2.1. Label Classes Table

A table displays all defined label classes with the following columns:
*   **Name:** The label class name (e.g., "Nuclei")
*   **Comments:** Optional comments or notes (displays "N/A" if empty)
*   **DateTime:** Timestamp of when the label class was created or last modified (displays "Date/time")
*   **No. GT labels:** Count of ground truth labels for this class (e.g., "0")
*   **Action:** Contains action buttons:
    *   **Edit button** (blue pencil icon) - Opens the label class editing interface
    *   **Delete button** (red trash icon) - Removes the label class after confirmation

#### 2.2.2. Add Label Class

*   A **Plus (+)** button appears next to the "Label Classes" header
*   Clicking opens a dialog for creating a new label class
*   **Label Class Creation:** Allows adding a new class by setting a **Name** (Value) and **Color**. Actions are **Cancel** and **Confirm**. Failure results in the error message: **Error: Failed to add new label class**
*   **Label Class Editing:** Allows modifying an existing class's **Name** (Value) and **Color**. The system may display a **Loading** state or an error status like **Error: Could not edit label class**


### 2.3. Image and Annotation Uploads

The **Images** section displays all images associated with the project and provides image management capabilities.

#### 2.3.1. Images Table

A comprehensive table lists all project images with the following columns:
*   **Thumbnail:** Small preview of the image (displays actual image content)
*   **Name:** File name (e.g., `image_file1.png`, `image_file2.svs`, `image_file3.png`)
*   **Dimensions:** Image resolution in pixels (e.g., `256×256` for standard images, `100,000×100,000` for whole slide images)
*   **No. Objects:** Count of annotated objects in the image (e.g., "0" for unlabeled images)
*   **Actions:** Contains action buttons for each image:
    *   **View/Edit button** (blue folder icon) - Opens the image for annotation or viewing
    *   **Delete button** (red trash icon) - Removes the image from the project

#### 2.3.2. Add Images

*   A **Plus (+)** button (pink/red square icon) appears in the table header
*   Clicking opens the **Upload Wizard** interface

#### 2.3.3. Upload Wizard

The Upload Wizard provides a structured, multi-step process for uploading images and annotations to a project.

##### Step 1: Approach

The first screen of the wizard allows users to select their preferred upload approach:

**Choose Upload Method:**
*   **Step by step** (radio button) - Guided workflow that walks through each upload step sequentially (images, masks, labels)
*   **File list** (radio button) - Upload all files at once using a comprehensive CSV file with the following columns:
    *   **Image Filename** - Name of the image file
    *   **Mask Filename** - (Optional) Name of the associated mask file
    *   **Label CSV Filename** - (Optional) Name of the associated label CSV file

**Step Progress Indicator:**
*   Once an upload method is selected (e.g., "Step by step"), a progress indicator appears at the top showing the 6 sequential wizard steps:
    1. **Approach** - Select the upload strategy
    2. **Upload Images** - Add image files to the project
    3. **Upload Masks** - (Optional) Add mask files
    4. **Upload Labels** - (Optional) Add annotation/label files
    5. **Review** - Verify all uploaded content before submission
    6. **Done** - Confirmation and completion
*   The current step is highlighted in bold, while future steps appear in gray

**Navigation:**
*   **Back** button - Return to the project dashboard (disabled on first step)
*   **Next** button - Proceed to the next step based on the selected approach
*   **Cancel** button - Exit the wizard without saving changes

##### Step 2: Upload Images

Users upload image files to the project. The step indicator shows "**2. Upload Images**" highlighted/underlined, with Step 1 completed (gray) and Steps 3-6 pending (gray).

**Choose Data Source:**

Users first select their preferred data source method:
*   **Upload Files** (radio button) - Select individual image files
*   **Upload Folder** (radio button) - Select an entire folder containing images

**File Upload Box:**

Once a data source option is selected, a bordered upload box appears containing:
*   **Header:** "Upload Image Files (.svs, .png, etc.)"
*   **Drop zone:** Interactive area with text "Drop files or click to upload"
*   **Supported formats:** `.svs` (whole slide images), `.png`, and other image formats
*   **File list area:** Where uploaded files are displayed

**Uploaded Files Display:**

As files are added, they appear in the upload box as a list showing:
*   File icon (document icon)
*   Filename (e.g., `image_file1.png`, `image_file2.png`, `image_file3.png`, `image_file4.png`)
*   **Remove button** (circled X icon) to delete a file from the upload queue

**Navigation:**
*   **Back** button - Return to the previous step (Approach)
*   **Next** button - Proceed to the next step (Upload Masks)
*   **Cancel** button - Exit the wizard without saving changes

##### Step 3: Upload Masks

This optional step allows users to upload mask files associated with their images. The step indicator shows "**3. Upload Masks**" highlighted/underlined.

**Upload Masks Decision:**

First, users decide whether to upload masks:
*   **Yes** (radio button) - Proceed with mask upload options
*   **No** (radio button) - Skip mask upload and proceed to next step

**Choose Data Source:**

If "Yes" is selected, users choose their data source method:
*   **Upload Files** (radio button) - Select individual mask files
*   **Upload Folder** (radio button) - Select an entire folder containing masks

**Mask Type:**

Users select the type of mask being uploaded:
*   **Geojson** (radio button) - GeoJSON format annotation files
*   **Binary Mask** (radio button) - Binary segmentation masks
*   **Multi-class Mask** (radio button) - Multi-class segmentation masks

**Mask Upload Box:**

Once all selections are made, a bordered upload box appears containing:
*   **Header:** "Upload Mask Files (.geojson, .json, .png)"
*   **Drop zone:** Interactive area with text "Drop files or click to upload"
*   **Supported formats:** `.geojson`, `.json`, `.png` depending on mask type selected
*   **File list area:** Where uploaded mask files are displayed

**Uploaded Masks Display:**

As files are added, they appear in the upload box as a list showing:
*   File icon (document icon)
*   Filename (e.g., `image_file1.geojson`, `image_file2.geojson`, `image_file3.geojson`, `image_file4.geojson`)
*   **Remove button** (circled X icon) to delete a file from the upload queue

**Navigation:**
*   **Back** button - Return to the previous step (Upload Images)
*   **Next** button - Proceed to the next step (Upload Labels)
*   **Cancel** button - Exit the wizard without saving changes

##### Step 4: Upload Labels

This optional step allows users to upload label or annotation files associated with their images. The step indicator shows "**4. Upload Labels**" highlighted/underlined.

**Upload Label CSVs Decision:**

First, users decide whether to upload label files:
*   **Yes** (radio button) - Proceed with label upload options
*   **No** (radio button) - Skip label upload and proceed to next step

**Choose Data Source:**

If "Yes" is selected, users choose their data source method:
*   **Upload Files** (radio button) - Select individual label files
*   **Upload Folder** (radio button) - Select an entire folder containing labels

**Label Upload Box:**

Once all selections are made, a bordered upload box appears containing:
*   **Header:** "Upload .csv Files"
*   **Drop zone:** Interactive area with text "Drop files or click to upload"
*   **Supported formats:** `.csv` files containing patch-level labels and annotations
*   **File list area:** Where uploaded label files are displayed

**Uploaded Labels Display:**

As files are added, they appear in the upload box as a list showing:
*   File icon (document icon)
*   Filename (e.g., `image_file1.csv`, `image_file2.csv`, `image_file3.csv`, `image_file4.csv`)
*   **Remove button** (circled X icon) to delete a file from the upload queue

**Navigation:**
*   **Back** button - Return to the previous step (Upload Masks)
*   **Next** button - Proceed to the next step (Review)
*   **Cancel** button - Exit the wizard without saving changes

**Note:** Label files update the **No. Objects** count for corresponding images in the project dashboard.

##### Step 5: Review

The Review step provides a comprehensive summary of all uploaded content before processing. The step indicator shows "**5. Review**" highlighted/underlined.

**Review Table:**

A table displays all files queued for import with the following columns:
*   **Image:** The image filename (e.g., `image_file_1.png`, `image_file_2.png`, `image_file_3.png`)
*   **Mask:** The associated mask filename if uploaded (e.g., `image_file_1.geojson`, `image_file_2.geojson`, `image_file_3.geojson`)
*   **CSV:** The associated label CSV filename if uploaded (e.g., `image_file_1.csv`, `image_file_2.csv`, `image_file_3.csv`)
*   **Error:** Displays validation error messages or "N/A" if no errors detected
*   **Status:** Shows the current processing state:
    *   **READY TO IMPORT** - File has passed validation and is ready to be processed
    *   **Spinner icon** - File is currently being processed (shown after clicking Process)
    *   **Check icon (✓)** - File has been successfully imported
    *   **Failure icon (✗)** - File import failed, check Error column for details

**Validation:**

The system performs validation checks to ensure:
*   File naming conventions match between images, masks, and CSVs
*   File formats are valid and supported
*   Required data fields are present
*   No conflicts with existing project data

**Navigation:**
*   **Back** button - Return to the previous step (Upload Labels)
*   **Process** button - Initiate the import process for all files
*   **Cancel** button - Exit the wizard without importing any files

**Processing Behavior:**

Once the **Process** button is clicked:
*   The Status column updates dynamically for each file as it's processed
*   Processing typically occurs sequentially through the file list
*   Users can monitor progress via the status icons
*   Any errors during processing are displayed in the Error column
*   After all files are processed successfully, the wizard advances to the Done step

##### Step 6: Done

*   Confirms successful upload completion
*   Updates the project dashboard with new images
*   Status shows **"Done"** upon successful processing

### 2.4. Open Labeling Page

A prominent button **"Open Labeling Page"** appears at the bottom right of the dashboard with an arrow icon.

*   **Requirements:** The button indicates **"Requires at least 2 label classes"** to proceed
*   **Action:** Clicking navigates to the interactive labeling interface where users can annotate patches within images
*   **State:** The button may be disabled if requirements are not met (less than 2 label classes defined)

### 2.5. Annotation Export

*   **Interface:** The `Export Labels` configuration dialog allows selection of formats.
*   **Export Formats:** Users can choose to export labels **Within ge json files** or **Within image-level csvs**.
*   **Status:** Once exported, the job status shows **Job running** and **File processing in progress**.

---

## 3. Labeling and Annotation Workflow

The labeling environment is accessed by the **Open Labeling Page** action.

### 3.1. Annotation Controls and Tools

*   **Tool Selection:** Available tools are **Move (1)** and **Lasso (2)**.
*   **Label Assignment Status:** The interface displays the current label assigned by keypress, for example, "Image Size ‘ENTER’ assigns label: **Lymphocyte**".
*   **Bulk Selection:** The option **Select all patches** is available.
*   **Use Case: Assign Labels:** The `Apply Label` menu allows assignment to predefined classes, such as **(1)Epithelial cell**, **(2) Lymphocyte**, and **(3) Other**.

### 3.2. Visualization and Filtering

The user can control the display of patches and labels using various options:

*   **Color By Ground Truth**
*   **Filter By Labeled**
*   **Include Label Classes** (e.g., Lymphocyte)
*   **Toggle Show Patches**

### 3.3. Navigation

The workflow includes navigation to an **Embedding** view.

---

## 4. Application and Project Configuration (Settings)

### 4.1. Configuration Sections

Settings are divided into two main categories: **Application Settings** and **Project Settings**.

### 4.2. Configurable Parameters

Key settings displayed in both Application and Project contexts include:
*   **Pad patches** (Value: True)
*   **Resize patches** (Value: False)
*   **Update embedding (s)** (Value: 5)

### 4.3. Actions and Feedback

*   **Actions:** The settings interface provides a **Reset** action.
*   **Status Feedback:** Confirmation messages appear upon completion, such as **Settings reset! The application settings have been reset.** or **Settings saved! The application settings have been saved.**.