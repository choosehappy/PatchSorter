# Technical Design Document: Patch Sorter Interface

## 1. Project Management & Overview

### 1.1. Projects Landing Page

#### 1.1.1. Implementation Details:
* **Frontend:** Use a table component (e.g., `DataTable`) to display project data. Columns include:
  - Project Name
  - Description
  - Date Created (DateTime format)
  - Number of Images
  - Number of Patches
  - Number of Label Classes
  - Actions (Edit Project, Delete Project buttons)
* **Backend:** Provide an API endpoint (`GET /projects`) to fetch the list of projects with all metadata.
* **Navigation:** 
  - Clicking on a project row navigates to the Project Dashboard (e.g., `/projects/:id`)
  - Implement routing for individual project views
* **UI/UX:** Display projects in a clear tabular format with sortable columns

---

### 1.2. Project Creation

#### 1.2.1. Implementation Details:
* **Frontend:** 
  - Display a **Plus (+)** button next to the `Projects` header to open the creation interface
  - Use a modal/dialog form with required fields:
    - **Project Name** (text input field, required)
    - **Project Description** (text area field, required)
  - Include a **Help** element/tooltip for user guidance
  - Provide **Create Project** button to submit
* **Backend:** 
  - Provide an API endpoint (`POST /projects`) to create a new project
  - Validate required fields (name and description)
  - Return created project with generated ID and metadata
* **Loading State:** Display a spinner or progress indicator labeled **Loading** while the project is being created
* **Error Handling:** Show appropriate error messages if creation fails

---

### 1.3. Project Deletion

#### 1.3.1. Implementation Details:
* **Frontend:** 
  - Use a confirmation modal dialog with the prompt: "**Are you sure you want to delete?**"
  - Include **Confirm** and **Cancel** buttons
  - Display **Loading** status during deletion process
  - Show **Error: error status** message upon failure
* **Backend:** Provide an API endpoint (`DELETE /projects/:id`) to delete a project and all associated data
* **Error Handling:** 
  - Display detailed error messages if the deletion fails
  - Handle cases where project is in use or has dependencies
* **Confirmation Flow:** Require explicit user confirmation before deletion to prevent accidental data loss

---

## 2. Project Dashboard & Asset Management

### 2.1. Project Details Display

#### 2.1.1. Implementation Details:
* **Frontend:** 
  - Display project details in a header component at the top of the dashboard:
    - **Name:** Project title (e.g., `Project Title` or `Project 1`)
    - **Description:** Project description text (e.g., `Project description displayed here.`)
  - Use prominent typography for visibility
* **Backend:** Fetch project details using an API endpoint (`GET /projects/:id`)
* **Responsive Design:** Ensure header displays properly on all screen sizes

---

### 2.2. Label Class Management

#### 2.2.1. Label Classes Table Implementation:
* **Frontend:** 
  - Use a table component to list all label classes with columns:
    - **Name:** Label class name (e.g., "Nuclei", "Epithelial cell", "Lymphocyte")
    - **Comments:** Optional notes (displays "N/A" if empty)
    - **DateTime:** Timestamp showing when class was created or last modified
    - **No. GT labels:** Count of ground truth labels for this class (e.g., "0")
    - **Action:** Action buttons column containing:
      - **Edit button** (blue pencil icon) - Opens label class editing interface
      - **Delete button** (red trash icon) - Removes the label class after confirmation
  - Display a **Plus (+)** button next to "Label Classes" section header
* **Backend:**
  - API endpoints:
    - `GET /projects/:id/label-classes` to fetch all label classes
    - `GET /projects/:id/label-classes/:classId` to fetch specific class details

#### 2.2.2. Label Class Creation:
* **Frontend:**
  - Clicking Plus (+) button opens a creation dialog with fields:
    - **Name** (text input, required)
    - **Color** (color picker component)
  - Provide **Cancel** and **Confirm** action buttons
  - Display error message: **Error: Failed to add new label class** on failure
* **Backend:** 
  - API endpoint: `POST /projects/:id/label-classes` to create a new label class
  - Validate uniqueness of label class names within project
  - Store RGB/hex color values
* **Validation:** Ensure label class names are unique and colors are valid

#### 2.2.3. Label Class Editing:
* **Frontend:**
  - Use similar form interface as creation for editing
  - Pre-populate fields with existing **Name** and **Color** values
  - Show **Loading** state during save operation
  - Display **Error: Could not edit label class** on failure
* **Backend:** 
  - API endpoint: `PUT /projects/:id/label-classes/:classId` to update a label class
  - Validate changes before applying
* **Constraints:** Ensure edits don't break existing annotations

---

### 2.3. Image and Annotation Management

#### 2.3.1. Images Table Implementation:
* **Frontend:** 
  - Display a comprehensive table with columns:
    - **Thumbnail:** Small preview image (actual image content)
    - **Name:** File name (e.g., `image_file1.png`, `image_file2.svs`, `image_file3.png`)
    - **Dimensions:** Image resolution in pixels (e.g., `256×256` for standard images, `100,000×100,000` for whole slide images)
    - **No. Objects:** Count of annotated objects/patches (e.g., "0" for unlabeled)
    - **Actions:** Action buttons for each image:
      - **View/Edit button** (blue folder icon) - Opens the image for annotation/viewing
      - **Delete button** (red trash icon) - Removes the image from the project
  - Display a **Plus (+)** button (pink/red square icon) in the table header
* **Backend:**
  - API endpoint: `GET /projects/:id/images` to fetch all images with metadata
  - Support pagination for large image collections
  - Include thumbnail generation service

#### 2.3.2. Upload Wizard - Architecture:
* **Overall Flow:** Multi-step wizard process accessed by clicking Plus (+) button
* **Progress Tracking:** Display step indicator showing: 1. Approach → 2. Upload Images → 3. Upload Masks → 4. Upload Labels → 5. Review → 6. Done
* **State Management:** Maintain wizard state across all steps with ability to navigate back
* **Navigation:** Provide **Back**, **Next**, and **Cancel** buttons on each step

#### 2.3.3. Step 1 - Approach Selection:
* **Frontend:**
  - Radio button selection for upload method:
    - **Step by step** - Guided workflow through sequential steps
    - **File list** - Upload all files at once using CSV manifest
  - For "File list" option, specify CSV format with columns:
    - Image Filename
    - Mask Filename (optional)
    - Label CSV Filename (optional)
  - Show step progress indicator after selection
* **Backend:**
  - Store user's approach selection in wizard state
  - Prepare appropriate validation rules based on selected approach
* **Validation:** Ensure one option is selected before allowing Next

#### 2.3.4. Step 2 - Upload Images:
* **Frontend:**
  - Display step indicator with "**2. Upload Images**" highlighted
  - Data source selection via radio buttons:
    - **Upload Files** - Select individual image files
    - **Upload Folder** - Select entire folder containing images
  - File upload box with:
    - Header: "Upload Image Files (.svs, .png, etc.)"
    - Drop zone with text "Drop files or click to upload"
    - Drag-and-drop support
  - Display uploaded files list showing:
    - File icon (document icon)
    - Filename (e.g., `image_file1.png`, `image_file2.png`)
    - **Remove button** (circled X icon) for each file
  - Support multiple file selection
* **Backend:**
  - API endpoint: `POST /projects/:id/images/upload-temp` for temporary file storage
  - Supported formats: `.svs` (whole slide images), `.png`, `.jpg`, `.tiff`, etc.
  - File validation for size, format, and integrity
  - Generate unique temporary IDs for files
* **File Processing:**
  - Client-side validation before upload
  - Chunked upload for large files
  - Progress indicators for each file

#### 2.3.5. Step 3 - Upload Masks:
* **Frontend:**
  - Display step indicator with "**3. Upload Masks**" highlighted
  - Initial decision radio buttons:
    - **Yes** - Proceed with mask upload
    - **No** - Skip mask upload and proceed to next step
  - If "Yes" selected, show:
    - Data source selection (Upload Files / Upload Folder)
    - Mask type selection:
      - **Geojson** - GeoJSON format annotation files
      - **Binary Mask** - Binary segmentation masks
      - **Multi-class Mask** - Multi-class segmentation masks
    - Upload box with header: "Upload Mask Files (.geojson, .json, .png)"
    - Drop zone: "Drop files or click to upload"
    - File list with remove buttons
* **Backend:**
  - API endpoint: `POST /projects/:id/masks/upload-temp` for temporary mask storage
  - Validate mask format based on selected type
  - Validate mask dimensions match corresponding images
  - Support formats: `.geojson`, `.json`, `.png` based on mask type
* **Validation:**
  - Verify mask files match uploaded images by filename convention
  - Check mask dimensions compatibility with images

#### 2.3.6. Step 4 - Upload Labels:
* **Frontend:**
  - Display step indicator with "**4. Upload Labels**" highlighted
  - Initial decision radio buttons:
    - **Yes** - Proceed with label CSV upload
    - **No** - Skip label upload and proceed to review
  - If "Yes" selected, show:
    - Data source selection (Upload Files / Upload Folder)
    - Upload box with header: "Upload .csv Files"
    - Drop zone: "Drop files or click to upload"
    - File list showing uploaded CSVs (e.g., `image_file1.csv`, `image_file2.csv`)
    - Remove button for each file
* **Backend:**
  - API endpoint: `POST /projects/:id/labels/upload-temp` for temporary label storage
  - Validate CSV format and required columns
  - Parse CSV to extract patch-level labels and annotations
  - Map labels to existing label classes
* **CSV Format Requirements:**
  - Define expected columns (e.g., patch_id, x, y, width, height, label_class)
  - Validate data types and ranges
* **Note:** Label files will update the **No. Objects** count for corresponding images

#### 2.3.7. Step 5 - Review:
* **Frontend:**
  - Display step indicator with "**5. Review**" highlighted
  - Review table with columns:
    - **Image:** Image filename (e.g., `image_file_1.png`)
    - **Mask:** Associated mask filename (e.g., `image_file_1.geojson`)
    - **CSV:** Associated label CSV filename (e.g., `image_file_1.csv`)
    - **Error:** Validation error messages or "N/A"
    - **Status:** Processing state icons:
      - **READY TO IMPORT** - Initial state after validation
      - **Spinner icon** - Currently being processed
      - **Check icon (✓)** - Successfully imported
      - **Failure icon (✗)** - Import failed
  - **Process** button to initiate import
  - Back and Cancel buttons
* **Backend:**
  - API endpoint: `POST /projects/:id/import/validate` for validation
  - API endpoint: `POST /projects/:id/import/process` to execute import
  - Validation checks:
    - File naming conventions match between images, masks, and CSVs
    - File formats are valid and supported
    - Required data fields are present
    - No conflicts with existing project data
  - Import process:
    - Move files from temporary to permanent storage
    - Generate thumbnails
    - Extract patches from images based on masks
    - Apply labels from CSVs
    - Update image metadata (No. Objects count)
* **Processing Behavior:**
  - Sequential processing through file list
  - Real-time status updates via WebSocket or polling
  - Display errors in Error column
  - Auto-advance to Done step when all files processed successfully
* **Error Recovery:**
  - Allow retry for failed imports
  - Provide detailed error messages for debugging

#### 2.3.8. Step 6 - Done:
* **Frontend:**
  - Display "**Done**" status
  - Show success message: "Upload completed successfully"
  - Provide button to return to Project Dashboard
  - Summary of imported items (X images, Y masks, Z labels)
* **Backend:**
  - Cleanup temporary files
  - Trigger any post-import processing (e.g., embedding generation)
* **Post-Processing:**
  - Update project dashboard with new images
  - Refresh image counts and statistics
  - Navigate back to dashboard on user confirmation

---

### 2.4. Open Labeling Page

#### 2.4.1. Implementation Details:
* **Frontend:**
  - Display prominent button labeled **"Open Labeling Page"** with arrow icon at bottom right of dashboard
  - Show requirement text: **"Requires at least 2 label classes"** below button
  - Disable button if less than 2 label classes are defined
  - Enable button styling to indicate active/disabled state
* **Backend:**
  - API endpoint: `GET /projects/:id/can-label` to check labeling requirements
  - Validate minimum label class count before allowing navigation
* **Navigation:** 
  - Route to labeling interface (e.g., `/projects/:id/label`)
  - Pass project context and available label classes
* **Requirements Validation:**
  - Minimum 2 label classes must be defined
  - At least 1 image must be uploaded
  - Display helpful error messages if requirements not met

---

### 2.5. Annotation Export

#### 2.5.1. Implementation Details:
* **Frontend:** 
  - Use a configuration dialog titled `Export Labels`
  - Provide format selection options:
    - **Within geojson files** - Export as GeoJSON format
    - **Within image-level csvs** - Export as CSV format per image
  - Include format-specific options (if applicable)
  - Show export button to initiate process
* **Backend:** 
  - API endpoint: `POST /projects/:id/export` to handle export requests
  - Support multiple export formats (GeoJSON, CSV)
  - Generate export files based on selected format
  - Package files for download (ZIP if multiple files)
* **Status Updates:** 
  - Display **Job running** status during export
  - Show **File processing in progress** message
  - Provide download link when complete
  - Show progress bar for large exports
* **Export Formats:**
  - GeoJSON: Full annotation geometry and properties
  - CSV: Tabular format with patch coordinates and labels
* **Error Handling:** 
  - Display errors if export fails
  - Provide retry option

---

## 3. Labeling and Annotation Workflow

### 3.1. Annotation Controls and Tools

#### 3.1.1. Implementation Details:
* **Frontend:**
  - Tool palette with selectable tools:
    - **Move (1)** - Pan and navigate the image canvas
    - **Lasso (2)** - Free-form selection tool for patches
  - Display keyboard shortcuts in UI (e.g., "Press 1 for Move, 2 for Lasso")
  - Show current tool state with visual highlighting
  - Label assignment status display showing: "Image Size 'ENTER' assigns label: **[Label Class Name]**"
  - Keyboard shortcut indicators for each label class (e.g., "(1)Epithelial cell", "(2) Lymphocyte", "(3) Other")
  - **Select all patches** checkbox/button for bulk operations
  - **Apply Label** dropdown menu listing all available label classes
* **Backend:** 
  - API endpoint: `PUT /projects/:id/annotations` to update patch labels
  - Support batch updates for multiple patches
  - Track annotation history for undo/redo functionality
* **Interaction Model:**
  - Click to select individual patches
  - Lasso tool for multi-select by drawing
  - Keyboard shortcuts for rapid labeling (number keys 1-9)
  - ENTER key to apply selected label to selection
* **Use Cases:**
  - Assign labels to individual or groups of patches
  - Bulk labeling with "Select all" feature
  - Quick keyboard-driven labeling workflow
* **Visual Feedback:**
  - Highlight selected patches
  - Show count of selected patches
  - Display current label assignment mode

---

### 3.2. Visualization and Filtering

#### 3.2.1. Implementation Details:
* **Frontend:**
  - Control panel with display options:
    - **Color By Ground Truth** - Toggle to color patches by their ground truth labels
    - **Filter By Labeled** - Show only patches with assigned labels
    - **Include Label Classes** - Multi-select dropdown to show/hide specific classes (e.g., "Lymphocyte")
    - **Toggle Show Patches** - Show/hide patch boundaries overlay
  - Checkbox or toggle switch for each option
  - Multi-select component for label class filtering
  - Color legend showing label class colors
* **Backend:**
  - API endpoint: `GET /projects/:id/images/:imageId/patches?filter=[params]` to fetch filtered patches
  - Support query parameters for filtering:
    - `labeled=true/false`
    - `labelClasses=[class1,class2,...]`
    - `colorBy=groundTruth/prediction`
* **Filtering Logic:**
  - Client-side filtering for responsive UI
  - Server-side filtering for large datasets
  - Combine multiple filters (AND logic)
* **Color Coding:**
  - Use label class colors for visualization
  - Different opacity for predictions vs ground truth
  - Highlight patches on hover
* **Performance:**
  - Efficient rendering for thousands of patches
  - Lazy loading for off-screen patches
  - Canvas-based rendering for performance

---

### 3.3. Navigation and View Controls

#### 3.3.1. Implementation Details:
* **Frontend:**
  - Navigation button/tab to switch to **Embedding** view
  - Breadcrumb navigation showing: Project > Image > View Mode
  - View mode switcher between:
    - Image View (default)
    - Embedding View (dimensionality reduction visualization)
  - Zoom controls for image canvas
  - Mini-map for large image navigation
* **Backend:**
  - API endpoint: `GET /projects/:id/embedding` to fetch embedding data
  - Generate or retrieve pre-computed embeddings
* **Routing:** 
  - `/projects/:id/label` - Image-based labeling view
  - `/projects/:id/embedding` - Embedding visualization view
  - Maintain state when switching between views
* **Embedding View:**
  - Display patches in 2D embedding space (e.g., UMAP, t-SNE)
  - Interactive scatter plot with patch thumbnails
  - Color by label class or prediction
  - Selection and labeling in embedding space

---

## 4. Application and Project Configuration (Settings)

### 4.1. Configuration Sections

#### 4.1.1. Implementation Details:
* **Frontend:** 
  - Use tabbed interface or collapsible sections to organize settings:
    - **Application Settings** tab/section - Global application preferences
    - **Project Settings** tab/section - Project-specific configurations
  - Clear visual separation between global and project-level settings
  - Help icons/tooltips for each setting explaining its purpose
* **Backend:** 
  - API endpoints:
    - `GET /settings` - Fetch application-level settings
    - `PUT /settings` - Update application-level settings
    - `GET /projects/:id/settings` - Fetch project-specific settings
    - `PUT /projects/:id/settings` - Update project-specific settings
  - Settings stored in database with versioning
  - Validate settings before applying
* **Settings Hierarchy:**
  - Application settings apply globally to all projects
  - Project settings override application defaults when specified
  - Clear indication of which settings are overridden

---

### 4.2. Configurable Parameters

#### 4.2.1. Implementation Details:
* **Frontend:** 
  - Settings controls for key parameters:
    - **Pad patches** - Toggle switch (Boolean, default: True)
      - Description: "Add padding around extracted patches"
    - **Resize patches** - Toggle switch (Boolean, default: False)
      - Description: "Resize patches to standard dimensions"
    - **Update embedding (s)** - Numeric input (Integer, default: 5)
      - Description: "Interval in seconds for embedding updates"
  - Use appropriate input types:
    - Toggle switches for boolean values
    - Number inputs with validation for numeric values
    - Dropdowns for enumerated options
  - Display current values clearly
  - Show default values in placeholder or help text
* **Backend:**
  - Validate parameter values:
    - Boolean fields: accept true/false
    - Numeric fields: validate range and type
    - Enum fields: validate against allowed values
  - Store settings with metadata (type, default, constraints)
  - Apply settings immediately or on confirmation based on parameter type
* **Parameter Types:**
  - **Pad patches:** Controls whether patches include padding pixels
  - **Resize patches:** Enables/disables patch resizing to uniform dimensions
  - **Update embedding (s):** Controls frequency of embedding recalculation
* **Additional Settings:**
  - Patch size configuration
  - Model selection for embeddings
  - Display preferences (theme, zoom levels)
  - Export format defaults

---

### 4.3. Actions and Feedback

#### 4.3.1. Implementation Details:
* **Frontend:** 
  - Action buttons at bottom of settings panel:
    - **Reset** button - Restore settings to defaults
    - **Save** button - Apply and save changes
  - Confirmation dialogs for destructive actions (Reset)
  - Success messages upon completion:
    - **Settings reset! The application settings have been reset.** (for application settings)
    - **Settings reset! The project settings have been reset.** (for project settings)
    - **Settings saved! The application settings have been saved.** (for application settings)
    - **Settings saved! The project settings have been saved.** (for project settings)
  - Error messages for failures with specific details
  - Visual indicators for unsaved changes
* **Backend:**
  - API endpoint: `POST /settings/reset` to reset to defaults
  - API endpoint: `POST /projects/:id/settings/reset` for project-specific reset
  - Transaction support for atomic updates
  - Return updated settings after save/reset
* **Feedback Mechanisms:**
  - Toast notifications for success/error messages
  - Loading spinners during save operations
  - Dirty state tracking (show which settings have changed)
  - Confirmation before navigating away with unsaved changes
* **Error Handling:** 
  - Display clear error messages for validation failures
  - Show which specific settings caused errors
  - Provide guidance on how to fix invalid settings
  - Rollback changes on save failure
* **User Experience:**
  - Auto-save option for non-critical settings
  - Undo/redo support for settings changes
  - Settings search/filter for large configuration sets
  - Import/export settings for backup and sharing

---

## 5. Technical Architecture Considerations

### 5.1. Frontend Technology Stack
* **Framework:** React or Vue.js for component-based UI
* **State Management:** Redux, Vuex, or similar for application state
* **UI Components:** Material-UI, Ant Design, or custom component library
* **Canvas Rendering:** Fabric.js or Konva.js for image annotation
* **Data Visualization:** D3.js or Plotly for embedding visualizations
* **File Uploads:** Resumable.js or similar for large file handling

### 5.2. Backend Technology Stack
* **Framework:** FastAPI (Python) or Express.js (Node.js)
* **Database:** PostgreSQL for relational data with PostGIS for spatial data
* **File Storage:** MinIO or S3 for object storage
* **Task Queue:** Celery or Bull for background processing
* **Real-time Updates:** WebSocket (Socket.io) for status updates
* **Image Processing:** OpenCV, Pillow, or similar libraries

### 5.3. Data Models
* **Project:** id, name, description, created_at, updated_at, settings
* **LabelClass:** id, project_id, name, color, comments, created_at
* **Image:** id, project_id, filename, path, dimensions, thumbnail_path, created_at
* **Mask:** id, image_id, filename, path, mask_type, created_at
* **Patch:** id, image_id, x, y, width, height, embedding_vector
* **Annotation:** id, patch_id, label_class_id, confidence, is_ground_truth, created_at

### 5.4. Performance Optimization
* **Image Tiling:** Serve large images as tiles for efficient rendering
* **Lazy Loading:** Load patches and annotations on-demand
* **Caching:** Redis for frequently accessed data
* **CDN:** Serve static assets and thumbnails via CDN
* **Database Indexing:** Optimize queries with proper indexes
* **Batch Operations:** Process multiple items in single requests

### 5.5. Security Considerations
* **Authentication:** JWT-based authentication for API access
* **Authorization:** Role-based access control (RBAC) for projects
* **File Validation:** Strict validation of uploaded file types and sizes
* **Input Sanitization:** Prevent SQL injection and XSS attacks
* **Rate Limiting:** Protect API endpoints from abuse
* **Data Encryption:** Encrypt sensitive data at rest and in transit
