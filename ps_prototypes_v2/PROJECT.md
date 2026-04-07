# Project: Active Learning Embedding Research (v2)

## Overview

This repository is the **research and algorithm development environment** for v2 of an active learning labeling tool. It is **not** the production deployment — the deployed system handles patch loading from whole-slide images, the user interface, and API endpoints. This codebase exists solely to iterate rapidly over large patch datasets, develop and validate the core embedding and loss algorithms, and port the final implementations into production.

**Scale target:** ≥ 1 billion objects.

---

## How the Tool Works

1. **Ingest** — Image patches are ingested in batches from a dataset.
2. **Embed** — Each patch is embedded into a 2D space via a deep learning model.
3. **Visualize** — The user views the 2D scatter plot and lassos regions of interest.
4. **Label** — The user reviews and applies class labels to selected points.
5. **Update** — Labels drive updates to both the embedding space and the prediction space.

---

## Loss Function

The model optimizes a composite loss with the following components:

| Component | Purpose |
|---|---|
| **Self-supervised loss** | Learns representations without labels |
| **2D layout loss** | Encourages well-structured placement in 2D space |
| **Homogeneity loss** | Pulls similar patches closer together |
| **Heterogeneity loss** | Pushes dissimilar patches further apart |
| **Supervised loss** | Strongly aligns the space with known labels; ensures class coherence and prediction quality |

---

## Key Engineering Constraint: Progressive Rendering

At billion-object scale, a full epoch before rendering is not acceptable. The system must support **progressive / streaming rendering**:

- Process one batch at a time.
- Compute 2D coordinates for each batch **immediately** upon embedding.
- Update the UI with new points in real time as batches arrive.
- If/when a full epoch completes, perform a full redraw and re-layout of all points.

This means the embedding model and 2D projection must be **online-capable** — producing valid coordinates incrementally, not only after a full pass over the data.

---

## Scope of This Repository

**In scope:**
- Embedding model architecture and training loop
- Composite loss function implementation and ablations
- Online / progressive 2D layout algorithm
- Batch processing pipeline (patches → embeddings → 2D coords)
- Benchmarking and validation across loss configurations

**Out of scope:**
- Whole-slide image patch extraction
- User interface
- API endpoints and server infrastructure
- Production deployment logic

---

## Goals

- [ ] Implement and validate each loss component independently
- [ ] Combine losses and tune weighting
- [ ] Achieve real-time batch-level 2D coordinate updates (progressive rendering)
- [ ] Validate embedding quality at scale (target: ≥1B objects)
- [ ] Produce clean, portable algorithm implementations ready for production integration