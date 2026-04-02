# Patch Array Storage Design

## 1. Patch Array Storage (TileDB / Zarr)
**The patch array is stored as a chunked, compressed multidimensional array using TileDB or Zarr. Each patch (tile) is indexed directly by the patch id (the primary key `id` column from the relational patch table defined in [db_technical_design.md]()).**

### 1.1. Array Schema

| Dimension    | Type         | Description                                                       |
| ------------ | ------------ | ----------------------------------------------------------------- |
| patch_id     | BIGINT       | Primary index; matches `id` field in the patch table (DB)         |

| Attribute    | Type         | Description                                                      |
| ------------ | ------------ | ----------------------------------------------------------------- |
| data         | uint8/float  | Raw patch data, typically shaped [height, width, channels]        |
| shape        | tuple(int)   | Shape of patch (height, width, channels)                          |
| dtype        | string       | Datatype of patch (e.g., uint8, float32)                          |
| image_id     | INT          | Foreign key for source image (optional, metadata attribute)        |

**Indexes:** The patch_id index enables direct lookup of patch data matching each database patch, O(1) access if storage engine supports it. Additional performance chunking may exist, but patch_id is the canonical key for integration.

## 2. User Operations Utilizing patch_array
1. Extract and store patches for a new image (batch/write, each assigned patch_id)
2. Retrieve a patch or batch of patches by patch_id for gallery or export
3. Stream patch tiles for user download or sharing

## 3. DL/System Operations Utilizing patch_array
1. Batch read of patch data for model training, using patch_id list
2. Parallel tile access for distributed inference or data loader
3. Chunked array writes for new patch batches (with preallocated patch_id ranges)
4. Integrity or completeness check using patch_id scan

## 4. Benchmarks

```{csv-table}
:header-rows: 1
:file: patch_storage_benchmarks.csv
```
