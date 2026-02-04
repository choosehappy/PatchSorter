# Image Patch Storage System Design

To efficiently store and manage image patches, we propose using a contiguous, batched storage solution such as TileDB or Zarr. These storage systems are well-suited for handling large-scale, multidimensional data, making them ideal for image patch storage.

### 1. Key Features

1. **Contiguous Storage**: Image patches will be stored in a contiguous manner to optimize read and write performance.
2. **Batched Storage**: Patches will be grouped into batches to improve data organization and retrieval efficiency.
3. **Append-Only**: The storage system will be designed to allow only append operations, ensuring data integrity and preventing accidental overwrites.
4. **Unique Identifiers**: Each image patch will be associated with a unique identifier to facilitate efficient indexing and retrieval.

### 2. Implementation Details

#### 2.1. Storage Format
- **TileDB**: A multi-dimensional array database optimized for sparse and dense data. It provides high performance for both read and write operations and supports advanced features like compression and cloud storage.
- **Zarr**: A format for the storage of chunked, compressed, N-dimensional arrays. It is simple, scalable, and supports parallel I/O.

#### 2.2. Data Model
- Each image patch will be stored as a multi-dimensional array (e.g., 3D array for RGB images: height x width x channels).
- Metadata will include:
  - Unique ID: A UUID or hash value to uniquely identify each patch.
  - Patch dimensions: Height, width, and number of channels.
  - Source image reference: Information about the original image from which the patch was extracted.
  - Additional metadata: Any other relevant information, such as patch coordinates, timestamp, or processing parameters.

#### 2.3. Data Model Characterization

The following table summarizes the data model for the image patch storage system:

| Field Name                 | Data Type   | Description                                                               |
| -------------------------- | ----------- | ------------------------------------------------------------------------- |
| **Unique ID**              | UUID/String | A unique identifier for each image patch.                                 |
| **Patch Dimensions**       | Tuple       | Dimensions of the patch (height, width, channels).                        |
| **Source Image Reference** | String      | Reference to the original image from which the patch was extracted.       |
| **Patch Coordinates**      | Tuple       | Coordinates of the patch within the source image (e.g., top-left corner). |
| **Timestamp**              | TIMESTAMP   | The time when the patch was created or processed.                         |
| **Additional Metadata**    | JSON        | Any other relevant information, such as processing parameters or tags.    |

#### 2.4. Append-Only Design
- New patches will be appended to the storage system without modifying existing data.
- The unique ID will be used to ensure no duplicate patches are added.
- Indexing will be updated dynamically to reflect the addition of new patches.

#### 2.5. Example Workflow
1. **Patch Extraction**: Image patches are extracted from larger images using a predefined grid or region of interest.
2. **Data Preparation**: Each patch is converted into a suitable format (e.g., NumPy array) and assigned a unique ID.
3. **Storage**: Patches are appended to the TileDB or Zarr storage system along with their metadata.
4. **Retrieval**: Patches can be efficiently retrieved using their unique IDs or metadata filters (e.g., by source image or spatial location).

#### 2.6. Advantages
- High performance for both read and write operations.
- Scalability to handle large datasets.
- Flexibility to store additional metadata.
- Data integrity through append-only operations.

### 3. Next Steps
- Evaluate the performance of TileDB and Zarr for the specific use case.
- Implement a prototype to test the append-only functionality and metadata indexing.
- Optimize the storage layout and chunking strategy for the expected workload.