# Relational DB Design

## 1. Database Tables
We separate ground truth and prediction data into distinct tables because:

- Old prediction data needs to be removed efficiently while keeping ground truth data intact.
- Ground truth data needs to be updated in-place, whereas prediction data is append-only.
- Some queries, e.g., lasso operation, require joining the ground and prediction labels for each patch returned.

### 1.1. Project Table
#### 1.1.1. Schema:
| Column Name     | Data Type | Description                         |
| --------------- | --------- | ----------------------------------- |
| **project_id**  | INT       | Identifier for the project, unique. |
| **name**        | TEXT      | Name of the project.                |
| **description** | TEXT      | Description of the project.         |
| **patch_size**  | INT       | The size of each patch.             |
| **create_ts**   | TIMESTAMP | Time when the project was created.  |


### 1.2. `agg_patch` Table

Each grid cell has multiple buckets representing each cell of a confusion matrix between ground truth and predicted labels.

```{note}
Consider making this an incremental materialized view using [pg_ivm](https://github.com/sraoss/pg_ivm).  
Docs indicate that IMVs are less effective when there are many updates to the base table.
```

#### 1.2.1. Schema:

| Column Name      | Data Type | Description                                |
| ---------------- | --------- | ------------------------------------------ |
| **grid_cell_id** | BIGINT    | Identifier for the grid cell.              |
| **bucket_date**  | TIMESTAMP | The date when the bucket was last updated. |
| **pred_label**   | INT       | Predicted label for the bucket.            |
| **gt_label**     | INT       | Ground truth label for the bucket.         |
| **count**        | INT       | Count of patches in the bucket.            |
| **pred_version** | INT       | Version of the prediction.                 |

### 1.3. `patch` Table

#### 1.3.1. Schema:

| Column Name     | Data Type | Description                                                |
| --------------- | --------- | ---------------------------------------------------------- |
| **patch_id**    | UUID      | Identifier for the patch, unique.                          |
| **gt_label**    | INT       | Ground truth label for the patch.                          |
| **gt_ts**       | TIMESTAMP | Time when the ground truth label was created/last updated. |
| **image_id**    | INT       | Identifier for the image containing the patch.             |
| **working_mag** | FLOAT     | The working magnification level of the patch.              |

### 1.4. `pred_patch` Table

#### 1.4.1. Schema:

| Column Name        | Data Type | Description                                        |
| ------------------ | --------- | -------------------------------------------------- |
| **id**             | UUID      | Identifier for the patch, unique.                  |
| **embed_x**        | FLOAT     | X coordinate of the patch embedding.               |
| **embed_y**        | FLOAT     | Y coordinate of the patch embedding.               |
| **grid_cell_id**   | BIGINT    | Identifier for the grid cell containing the point. |
| **event_ts**       | TIMESTAMP | Time when the point was appended.                  |
| **pred_label**     | INT       | Predicted label for the point.                     |
| **pred_ts**        | TIMESTAMP | Time when the prediction was made.                 |
| **pred_version**   | INT       | Version of the prediction.                         |
| **label_class_id** | INT       | Identifier for the class of the label.             |
| **patch_coords**   | JSON      | Coordinates of the patch within the image.         |

### 1.5. `image` Table

#### 1.5.1. Schema:
| Column Name         | Data Type | Description                            |
| ------------------- | --------- | -------------------------------------- |
| **image_id**        | INT       | Identifier for the image, unique.      |
| **project_id**      | INT       | Project identifier. Foreign Key        |
| **name**            | TEXT      | Name of the image.                     |
| **image_path**      | TEXT      | File path or URI of the image.         |
| **upload_ts**       | TIMESTAMP | Time when the image was uploaded.      |
| **base_mag**        | FLOAT     | Base magnification level of the image. |
| **base_width**      | INT       | Width of the image in pixels.          |
| **base_height**     | INT       | Height of the image in pixels.         |
| **dz_tilesize**     | INT       | Tile size used in DeepZoom format.     |
| **embedding_coord** | POINT     | Image embedding from CohortFinder      |
| **group_id**        | INT       | Group id from CohortFinder             |
| **split**           | INT       | Split from CohortFinder                |

### 1.6. `label_class` Table
#### 1.6.1. Schema:
| Column Name        | Data Type | Description                                         |
| ------------------ | --------- | --------------------------------------------------- |
| **label_class_id** | INT       | Identifier for the label class, unique.             |
| **project_id**     | INT       | Identifier for the project, Foreign Key             |
| **name**           | TEXT      | Name of the label class.                            |
| **color**          | TEXT      | Color associated with the label class.              |
| **event_ts**       | TIMESTAMP | Time when the label class was created/last updated. |

## 2. User Operations

### 2.1. Patch Extraction
- When patches are first extracted from images, they will be appended to the patch table with null ground truth labels.
- A customizeable script will handle the extraction approach (e.g., crop, resize, or strided), resulting in an output array of patch objects, each following the schema of the patch table. A bulk insert operation will be performed on the patch table.


### Update ground truth labels
Each time the user updates ground truth labels for patches (e.g., via the patch gallery):
- Upsert the `gt_label` in the patch table for specific `patch_id`s as needed.

### 2.2. Lasso Query
Each time the user performs a lasso operation to select patches:

- Join ground truth and prediction tables on `patch_id` to retrieve combined labels for selected patches.

### 2.3. Toggle show patches

When the user requests to view a representative patch for a set of grid cells (< 1000 grid cells):
- Get patches from the prediction table for the specified grid cells, limiting to one patch per grid cell.

### 2.4. Assign & Reassign Ground Truth Labels

Each time the user assigns labels to patches (e.g., via the patch gallery):

- Upsert the `ground_truth_label` in the ground truth table for specific `patch_id`s as needed.

## 3. DL Operations


### 3.1. Insert New Predictions

Each time a DL worker produces new predictions:

- Append new prediction data to the prediction table with the latest `pred_version`.
- Update the aggregation table by incrementing counts in the corresponding buckets.

### 3.2. Remove Old Predictions

When the prediction table becomes "full," i.e., the total count of rows equals the total number of patches in the dataset:

1. Increment a global value for `pred_version`.
2. Drop partitions of the prediction table where `pred_version` is less than the latest version.

## 4. Prototypes
```{csv-table}
:header-rows: 1
:file: db_prototypes.csv
```