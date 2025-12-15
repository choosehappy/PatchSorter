# Technical Design Document: Patch Sorter Interface

## 1. Project Management & Overview

### 1.1. Projects Landing Page

#### 1.1.1. Implementation Details:
* **Frontend:** Use a table component (e.g., `DataTable`) to display project data. Columns include:
  - Project Name
  - DateTime
  - Number of Images
  - Number of Label Classes
  - Actions (e.g., View, Edit, Delete)
* **Backend:** Provide an API endpoint (`GET /projects`) to fetch the list of projects.
* **Navigation:** Implement routing to navigate to the detailed project view (e.g., `/projects/:id`).

---

### 1.2. Project Creation

#### 1.2.1. Implementation Details:
* **Frontend:** Use a form with fields for Project Name and Project Description. Include a Help tooltip for guidance.
* **Backend:** Provide an API endpoint (`POST /projects`) to create a new project.
* **Loading State:** Display a spinner or progress indicator while the project is being created.

---

### 1.3. Project Deletion

#### 1.3.1. Implementation Details:
* **Frontend:** Use a modal dialog for confirmation. Include Confirm and Cancel buttons.
* **Backend:** Provide an API endpoint (`DELETE /projects/:id`) to delete a project.
* **Error Handling:** Display error messages if the deletion fails.

---

## 2. Project Dashboard & Asset Management

### 2.1. Project Details Display

#### 2.1.1. Implementation Details:
* **Frontend:** Display project details (name and description) using a header component.
* **Backend:** Fetch project details using an API endpoint (`GET /projects/:id`).

---

### 2.2. Label Class Management

#### 2.2.1. Implementation Details:
* **Frontend:** Use a table to list label classes with columns for Name, DateTime, Number of GT Labels, and Actions.
* **Label Class Creation:**
  - Use a form with fields for Name and Color.
  - Provide Cancel and Confirm buttons.
* **Label Class Editing:**
  - Use a similar form for editing existing classes.
* **Backend:**
  - API endpoints:
    - `GET /projects/:id/label-classes` to fetch label classes.
    - `POST /projects/:id/label-classes` to create a new label class.
    - `PUT /projects/:id/label-classes/:classId` to edit a label class.
* **Error Handling:** Display appropriate error messages for failures.

---

### 2.3. Image and Annotation Uploads

#### 2.3.1. Implementation Details:
* **Frontend:**
  - Use a drag-and-drop file upload component.
  - Display uploaded images in a table with columns for Thumbnail, Name, Dimensions, Number of Objects, and Actions.
* **Backend:**
  - API endpoints:
    - `POST /projects/:id/images` for image uploads.
    - `POST /projects/:id/annotations` for annotation uploads.
* **File Processing:**
  - Show progress indicators for file processing.
  - Handle `.tsv` uploads with a dedicated processing job.
* **Error Handling:** Display error messages for failed uploads or processing.

---

### 2.4. Annotation Export

#### 2.4.1. Implementation Details:
* **Frontend:** Use a dialog to configure export options (e.g., format selection).
* **Backend:** Provide an API endpoint (`POST /projects/:id/export`) to handle export requests.
* **Status Updates:** Display progress indicators for export jobs.

---

## 3. Labeling and Annotation Workflow

### 3.1. Annotation Controls and Tools

#### 3.1.1. Implementation Details:
* **Frontend:**
  - Implement tools like Move and Lasso for annotation.
  - Display the current label assignment status.
  - Provide a bulk selection option.
* **Backend:** Update annotations using an API endpoint (`PUT /projects/:id/annotations`).

---

### 3.2. Visualization and Filtering

#### 3.2.1. Implementation Details:
* **Frontend:**
  - Add controls for filtering and toggling display options.
  - Implement color-coding for ground truth labels.
* **Backend:** Fetch filtered data using query parameters in API requests (e.g., `GET /projects/:id/images?filter=labeled`).

---

### 3.3. Navigation

#### 3.3.1. Implementation Details:
* **Frontend:** Implement navigation to the Embedding view using routing (e.g., `/projects/:id/embedding`).

---

## 4. Application and Project Configuration (Settings)

### 4.1. Configuration Sections

#### 4.1.1. Implementation Details:
* **Frontend:** Use tabs or collapsible sections for Application Settings and Project Settings.
* **Backend:** Fetch and update settings using API endpoints:
  - `GET /settings` for application settings.
  - `GET /projects/:id/settings` for project settings.
  - `PUT /settings` and `PUT /projects/:id/settings` for updates.

---

### 4.2. Configurable Parameters

#### 4.2.1. Implementation Details:
* **Frontend:** Use toggle switches or dropdowns for parameters like Pad Patches, Resize Patches, and Update Embedding.
* **Backend:** Validate and save settings via the respective API endpoints.

---

### 4.3. Actions and Feedback

#### 4.3.1. Implementation Details:
* **Frontend:** Provide Reset and Save buttons.
* **Feedback:** Display confirmation messages upon successful actions.
* **Error Handling:** Show error messages for failed actions.
