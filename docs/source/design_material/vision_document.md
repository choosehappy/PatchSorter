<style>
.reveal section {
  font-size: 20px;
  text-align: left;
}
</style>

# PatchSorter v2.0: Vision Document

## 1. Document Purpose

The purpose of this document is:

1. Introduce the general motivations for developing PatchSorter (PS) v2.0  
2. Identify core areas of functionality  
3. Catalogue existing technical knowledge and unknowns requiring research and prototyping  

**Definitions:**  
- **QA**: QuickAnnotator (annotation system)  
- **PS**: PatchSorter (labeling system — to avoid confusion, we will consistently use "labeling" for PS and "annotating" for QA, as suggested in review comments)  

---

## 2. General Goals & Motivation

PS v2.0 is designed to support efficient **labeling** of extremely large-scale histologic datasets, enabling an active learning workflow for labeling, training, and prediction at a scale of up to **1 billion segmented histologic objects**.  

Peripheral goals include:

- Support Whole Slide Images (WSI) and geojson, compatible with QA v2.0  
- Couple patches with annotations in QA (e.g., select annotations in QA and label respective patches in PS, or click on a patch in PS and view the annotation in QA).  
  - To avoid complexity, it may be easier to store **XY coordinates** of each patch so that the ROI can be viewed on the WSI.  
- Standardize and improve the API: external clients (e.g., mobile labeling tools, LabelStudio) should be able to consume the PatchSorter API to receive patch data and submit labels  
- Integrate with **Ray** for parallelized training, prediction, and other intensive operations  
- Facilitate initial **UI prototyping**: quick-and-dirty prototypes of basic user stories are needed early to avoid technology lock-in issues that may prevent later UI flexibility  

---

## 3. Core Functionality

### 3.1. Importing Data

**Functionality & Constraints**  

PatchSorter must support uploading image and object segmentation data with the following constraints:  

- Compatible with both standard image formats and WSIs  
- Accept slide-level geojson annotation files, for importing annotations from arbitrary (non-QA) workflows  
- If a project already exists in QA, PS should support efficient upload by:  
  - Avoiding data duplication wherever possible (e.g., link directly to QA’s NAS storage)  
  - Efficiently copying tables into PS  
  - Assume QA database and file storage are network-accessible  
- Postconditions
    - Each patch will be stored in the PS db with subtype information (both gt and pred) and origin information (parent annotationclass, image, project)

**Knowns**  
- Compatibility between PS and QA requires storing subtype GT/Pred and embedded coordinates with a spatial index (e.g., hierarchical tile index), and WSI + project ids.
- PS should not use the QA database. All project, image, and patch information should be imported via one of two upload options.
- **Primary upload option (default):** upload patches using annotation geojson files.
  - 1 geojson file per image is uploaded.
- **Secondary upload option:** direct connection between QA and PS applications for data transfer.
  ```{admonition} Post-MVP Feature
  :class: note
  This feature is planned for after the MVP release.
  ```
  - Define import API endpoint within PS similar to the DSA annotation import endpoint.
  - Stream data into PS from QA.



**Unknowns**  
N/A

---

### 3.2. Data Loading

**Functionality & Constraints**  
Mechanism for loading patch data into distributed DL models for training.  

**Knowns**  
- Tiered storage solution for feature vectors:  
  - Tier 1: pre-extracted feature vectors stored in db (with caching)  
  - Tier 2: read patch region from WSI and extract features  
  vectors  
- Same WSI storage structure as QA (NAS accessible)  
- GT/Pred labels, embedded coordinates, and patch pointers must be efficiently stored  

**Unknowns**  

- Should PS cache tiles as QA does, or directly rely on WSI reads?  
- How to handle histologic objects of **varied sizes**?  
  - Possible: configurable padding setting for patch extraction  
- Should each WSI have its own database for distributed querying?  
- How to efficiently store and query **feature vectors**?  

---

### 3.3. Training

**Functionality & Constraints**  

- Active learning loop: PS continuously trains and generates predictions + embeddings  
- Distributed training with Ray (as in QA), with workers spread across GPUs  
- Train-pred loop: generate predictions & embeddings before each training cycle  
- GT labels assigned in real-time  

**Knowns:**  

- Consider training a **self-supervised model (SSL/auto-encoder)** to reduce raw patch dimensions into feature vectors (e.g., $32 \times 32 \times 3 = 3072$ dims $\rightarrow$ 256 dims). This allows PS to operate in reduced feature space, improving scalability.  
- PS usage patterns differ from QA:  
  - In QA, only a few tiles per WSI are reviewed at once, so caching works well  
  - In PS, all patches may need frequent re-embedding → caching may not be sufficient (need hybrid RAM + HDD database-backed cache)  

**Unknowns**  

- Should we explore training a **Graph Neural Network (GNN)** alongside the CNN feature extractor?  

---

### 3.4. Embedding

**Functionality & Constraints**  
Embedded points must support:  
- Fast insertions (≥100,000 points/sec)  
- Hierarchical views of the distribution  
- Configurable number of dimensions  
- Efficient visualization  

**Knowns**  

- Parametric UMAP allows incremental updates but requires all data in memory during training  
- Transformers can be leveraged for scalable dimensionality reduction  
- Normal UMAP is not scalable (benchmark: ~27min for 1M points)  

**Unknowns**  

- Should embedding be **two-stage** (feature extraction + embedding) or transformer → embedding?  
- Should embedding methods be **modular and swappable**?  
- For scalability:  
  - Small datasets → direct UMAP  
  - Large datasets (up to 1B points) → random projection + downsampling + learned embedding function  


**Technical Notes**

- H3 library for hierarchical, hexagonal indexing.
- S2 library for square indexing.

---

### 3.5. Prediction

Each patch must be mapped to a predicted subtype label. Predictions can:  

- Suggest ground truth labels to users  
- Identify discrepancies between predicted and GT labels, prompting model refinement  

---

### 3.6. Visualizing the Patch Distribution

**Constraints:**  

- Must differentiate subtypes (e.g., color)  
- Embed in 2D with user-selectable dimensions  
- Apply filters (all, labeled, unlabeled, discordant, class, GT vs PRED)  
- Must support density visualization without losing sparse data  
- Update UI frequently and with low latency:  
  - ≤200ms for rendering updates  
  - ≤50ms network latency expected  
  - New labels applied should update in ≤200ms  
- Implement incremental visualization: show a fast 10% sample first, then progressively refine (e.g., singletons vs hyperpoints)  

**Knowns:**  

- Use checkbox-based logical filters (e.g., show only Class1 GT + Class2 Pred)  
- Client should poll or be pushed updated point data  
- Hover interactions: when hovering on bins/regions, backend should fetch representative patches (e.g., last-added patch in a bin)  
- Global patch view: show representative patches from across the distribution.

**Unknowns:**  

- Exact method of fast visualization (Datashader, 2D histograms, MVT, PostGIS spatial indexes)  
- Best way to represent multiple classes in binned visualization  

---

### 3.7. Labeling

**Constraints:**  

- Apply single or bulk labels  
- Lasso select multiple patches  
- Prioritize difficult cases  

**Considerations:**  

- Should labeling occur directly in the embedding viewport or in a dedicated pane?  
- Infinite scroll preferred over pagination for patch images  
- Efficient lasso queries (e.g., via PostGIS HexagonGrid)  
- "Label all" option for large query results (e.g., lasso returns 100k patches, label subset then apply to rest)  

---

### 3.8. Export Labels

**Constraints:**  

- Store up to 1B labeled objects  
- Export subtyped annotations grouped by image (e.g., for QuPath)  
- Digital Slide Archive (DSA) compatibility  
- Support re-import of PS’s own exports  

**Implementation Notes:**  

- OGR library for progressive geojson export  
- Ray actors for parallelized export, with manifest files for download links  

---