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
### 2.1. Extract and store patches for a new image
How quickly can a whole slide image be processed into patches and stored in the patch array? Does the append time scale linearly with the size of the array?


### 2.2. Retrieve a patch or batch of patches by patch_id
How quickly can we retrieve a single patch or batch of patches by their patch_id? We need to retrieve 1000 patches in under 1 second to be displayed in the patch gallery UI. 

## 3. DL/System Operations Utilizing patch_array
### 3.1. Batch read of patch data for model training
How quickly can a dataloader retrieve a batch of contiguous or random patches by patch_id? 

Does performance degrade as the patch array grows?

### 3.3. Chunked array writes for new patch batches
In the case that we store intermediate feature vectors into a separate attribute in the patch array, how quickly can we update a batch of feature vectors for a preallocated patch_id range? This is relevant for storing intermediate features during model training or inference.

## 4. Benchmarks

```{csv-table}
:header-rows: 1
:file: patch_storage_benchmarks.csv
```
