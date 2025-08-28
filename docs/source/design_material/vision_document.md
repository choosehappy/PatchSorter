# PatchSorter v2.0: Vision Document

## 1. Document Purpose

The purpose of this document is:

- Introduce the general motivations for developing PatchSorter (PS) v2.0
- Identify core areas of functionality
- Catalogue existing technical knowledge and unknowns requiring research and prototyping.

**Definitions**:  
- **QA**: QuickAnnotator  
- **PS**: PatchSorter  

---
## 2. General Goals & Motivation

PS v2.0 is designed to support efficient labeling of extremely large-scale histologic datasets, enabling an active learning workflow for labeling, training, and prediction at a scale of up to **1 billion segmented histologic objects**.

Peripheral goals:

- Support Whole Slide Images and GeoJSON, compatible with QA v2.0  
- Couple patches with annotations in QA  
  - Select annotations in QA and label the respective patches in PS  
  - Click on a patch in PS and view the respective annotation in QA  
  - Direct coupling may be complex → alternative: store XY coords of each patch so ROI can be viewed on the WSI  
- Standardize and improve API  
  - External clients (e.g., mobile labeling tool, LabelStudio) should consume PS API to receive patch data and submit labels  
- Integrate with Ray for parallelized training, prediction, and other intensive operations  

---

## 3. Core Functionality

### 3.1 Importing Data

**Functionality & Constraints**

- Upload image and object segmentation data to PS  
- Must be compatible with standard image formats **and** WSIs  
- Must accept slide-level GeoJSON annotation files  
- Efficient upload if project already exists in QA:  
  - Avoid moving image data over the network  
  - Access QA database directly or copy tables efficiently  
  - Avoid duplication if possible  

**Knowns**: –  

**Unknowns**:  
- What queries/storage operations are required at object level?  
- Should subtype GT/Pred be stored?  
- Should embedded coordinates use a spatial index/hierarchical tile index?  

---

### 3.2 Data Loading

**Functionality & Constraints**  
Mechanism for loading patch data into distributed DL training.

**Knowns**:

- **Storage of image data**  
  - Tiered storage:  
    - Tier 1: memcached  
    - Tier 2: pre-extracted patches  
    - Tier 3: read patch region from WSI  
  - Option: database storage with caching  
  - Option: avoid storing patches, store feature vectors instead  
- Same WSI storage structure as QA (NAS read access assumed)  
- Store: feature vectors, GT/Pred labels, embedded coordinates, pointer to patch  

**Unknowns (Moderate)**:  
- Should QA’s patch loading strategy (direct from WSI + caching) be reused?  
- Centralized vs decentralized DB (Postgres vs CockroachDB)?  
- How to store feature vectors for large histologic objects?  
- Should there be configurable padding when extracting patches?  

---

### 3.3 Training

**Functionality & Constraints**  
Govern PS’s active learning abilities: continuous training + predictions + embeddings in loop.

**Knowns**:

- Use Ray for distributed training (fractional GPU spreading supported)  
- Workers likely sample randomly from training set  
- Train-pred loop for conditional predictions + embeddings before each cycle  
- GT labels assigned in real-time  

**Unknowns (Moderate)**:  
- Should a GNN be trained alongside the CNN feature extractor (“GraphSorter”)?  

---

### 3.4 Embedding

**Functionality & Constraints**  

- Must rapidly insert (e.g., 100k points/sec)  
- Must rapidly return hierarchical views of regions  
- Approach should allow customization (#dimensions configurable)  

**Knowns**:

- Parametric UMAP enables mapping new vectors without retraining full space  
- Normal UMAP not scalable (30s for 10k → 27min+ for 1M)  
- Transformers can be used for scalable dimensionality reduction  

**Unknowns**:

- One-stage (direct transformer → coords + label) vs two-stage (feature extraction + DR)?  
- Should embedding approaches be hot-swappable?  
- Best storage paradigm for scalability:  
  - S2 or H3 with PostGIS  
  - Hierarchical binning (bin counts updated on insert)  
  - Dynamic bin counts/raster tiles  

---

### 3.5 Prediction

**Functionality & Constraints**  

- Each patch mapped to predicted subtype label  
- Pred label used to:  
  - Suggest GT labels to user  
  - Identify pred-GT discrepancies for refinement  

**Knowns**: –  
**Unknowns (Low)**: –  

---

### 3.6 Visualizing the Patch Distribution

**Functionality & Constraints**  

- Visual representation of entire patch distribution  
- Requirements:  
  - Differentiate subtypes (e.g., color)  
  - Embedding shows 2 dims at a time (user controlled)  
  - Conditional coloring by GT or Pred label  
  - Filters: All / Labeled / Unlabeled / Discordant / GT vs Pred / Class  
  - Capture density info for subtypes  
  - Update UI frequently (<200ms for viewport updates, <5s on embedding refresh)  
  - Latency budget includes network (<50ms)  

**Knowns**: –  

**Unknowns (High)**:  
- Serverside rendering almost certainly required (Datashader recommended)  
- Binned statistics may be preferable to raw points  
- Consider PostGIS, H3, S2, MVT tiling strategies  

---

### 3.7 Labeling

**Functionality & Constraints**  

- Query patches in ROI and apply labels  
- Features:  
  - Single/bulk labels  
  - Prioritize difficult cases  
  - Lasso selection supported  

**Knowns**: –  

**Unknowns (Moderate)**:  
- Should users view additional context in WSI viewer?  
  - Pros: context may improve prioritization  
  - Cons: slows down labeling, patch size may be too small  
- Should labeling occur in distribution viewport or a separate pane?  
- Infinite scroll vs pagination for patch list?  
- Efficient queries for lassoed regions (e.g., ST_HexagonGrid + geohash)  

---

### 3.8 Export Labels

**Functionality & Constraints**  

- Scale: up to 1B labeled objects in DB  
- Must support export for DL workflows  
- Constraints:  
  - Group labels by image (e.g., QuPath compatibility)  
  - Digital Slide Archive compatibility  
  - PS should ingest its own export format  

**Knowns**:

- `ogr` library supports progressive writing to GeoJSON  
- Ray actors can parallelize export and generate manifest file with download links  

**Unknowns**: –  