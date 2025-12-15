# Design Document: Patch Sorter Interface

## 1. Project Management & Overview

### 1.1. Projects Landing Page

The main landing page lists existing projects in a tabular format.

*   **Data Display Components:** The project list table includes columns for **Project Name**, **DateTime**, **# of images**, **# of label classes**, and an **Action** column.
*   **Use Case: Enter Project Page:** Allows navigation from the list of projects (e.g., `Project 1`, `Project 2`, etc.) to the detailed project view.

### 1.2. Project Creation

Project configuration is handled under the `New Project` interface.

*   **Required Inputs:** Users must configure the **Project Name** (Value) and **Project Description** (Value). A **Help** element is also present.
*   **Actions and Status:** The creation process is initiated by the **Create Project** button. A **Loading** state is shown while the project is being created.

### 1.3. Project Deletion

Deletion is confirmed via a dedicated dialog.

*   **Interface:** The `Delete Project` dialog prompts the user with the question: "**Are you sure you want to delete?**".
*   **Actions and Status:** Actions include **Confirm** and **Cancel**. Status indicators show **Loading** during the deletion process or display an **Error: error status** upon failure.

---

## 2. Project Dashboard & Asset Management

### 2.1. Project Details Display

*   **Headers:** Displays the project name (e.g., `Project Title` or `Project 1`) and the description (`Project description displayed here.`).

### 2.2. Label Class Management

This section lists and manages the types of objects that can be labeled.

*   **Data Display:** Label classes are listed showing the **Label Class Name**, **DateTime**, **# GT labels**, and an **Action** column. Examples of classes include Nuclei, Lymphocyte, and Other.
*   **Label Class Creation:** Allows adding a new class by setting a **Name** (Value) and **Color**. Actions are **Cancel** and **Confirm**. Failure results in the error message: **Error: Failed to add new label class**.
*   **Label Class Editing:** Allows modifying an existing class's **Name** (Value) and **Color**. The system may display a **Loading** state or an error status like **Error: Could not edit label class**.

### 2.3. Image and Annotation Uploads

The interface allows uploading files via **Drop files or click to upload**. Supported formats are **geojson, Image/WSI, or .tsv**.

*   **Image Listing:** Images are listed with **Thumbnail**, **Name**, **Dimensions**, **# Objects**, and **Actions**. Dimensions can vary widely, such as 256x256 for `.png` files and 100,000x100,000 for `.svs` files.

*   **Use Case: Manually Upload (Images/Annotations):**
    *   Image files (e.g., `image_file1.png`) are uploaded using **Upload Files**. Upon completion, the status shows **Done**.
    *   Geojson files (e.g., `image_file1_annotations.geojson`) can be uploaded to add annotations, which updates the `# Objects` count for the corresponding image (e.g., from 0 to 1).

*   **Use Case: TSV Upload:** Uploading a `.tsv` file (e.g., `example.tsv`) initiates a processing job. The status displays **Job running** and **File processing in progress**. Errors during processing are indicated by messages like **Failed subtask name**.

### 2.4. Annotation Export

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