# Relational DB Design

## 1. Database Tables
We separate ground truth and prediction data into distinct tables because:

- Old prediction data needs to be removed efficiently while keeping ground truth data intact.
- Ground truth data needs to be updated in-place, whereas prediction data is append-only.
- Some queries, e.g., lasso operation, require joining the ground and prediction labels for each patch returned.


### 1.1. `agg_patch` Table

Each grid cell has multiple buckets representing each cell of a confusion matrix between ground truth and predicted labels.

> **Note:** Consider making this an incremental materialized view using [pg_ivm](https://github.com/sraoss/pg_ivm).  
> Docs indicate that IMVs are less effective when there are many updates to the base table.

#### 1.1.1. Schema:

| Column Name      | Data Type | Description                                |
| ---------------- | --------- | ------------------------------------------ |
| **grid_cell_id** | BIGINT    | Identifier for the grid cell.              |
| **bucket_date**  | TIMESTAMP | The date when the bucket was last updated. |
| **pred_label**   | INT       | Predicted label for the bucket.            |
| **gt_label**     | INT       | Ground truth label for the bucket.         |
| **count**        | INT       | Count of patches in the bucket.            |
| **pred_version** | INT       | Version of the prediction.                 |

### 1.2. `gt_patch` Table

#### 1.2.1. Schema:

| Column Name  | Data Type | Description                                                |
| ------------ | --------- | ---------------------------------------------------------- |
| **patch_id** | UUID      | Identifier for the patch, unique.                          |
| **gt_label** | INT       | Ground truth label for the patch.                          |
| **gt_ts**    | TIMESTAMP | Time when the ground truth label was created/last updated. |

### 1.3. `pred_patch` Table

#### 1.3.1. Schema:

| Column Name        | Data Type | Description                                        |
| ------------------ | --------- | -------------------------------------------------- |
| **patch_id**       | UUID      | Identifier for the patch, unique.                  |
| **embed_x**        | FLOAT     | X coordinate of the patch embedding.               |
| **embed_y**        | FLOAT     | Y coordinate of the patch embedding.               |
| **grid_cell_id**   | BIGINT    | Identifier for the grid cell containing the point. |
| **event_ts**       | TIMESTAMP | Time when the point was appended.                  |
| **pred_label**     | INT       | Predicted label for the point.                     |
| **pred_ts**        | TIMESTAMP | Time when the prediction was made.                 |
| **pred_version**   | INT       | Version of the prediction.                         |
| **label_class_id** | INT       | Identifier for the class of the label.             |
| **patch_coords**   | JSON      | Coordinates of the patch within the image.         |

## 2. User Operations


### 2.1. Lasso Query
Each time the user performs a lasso operation to select patches:

- Join ground truth and prediction tables on `patch_id` to retrieve combined labels for selected patches.

### 2.2. Toggle show patches

When the user requests to view a representative patch for a set of grid cells (< 1000 grid cells):
- Get patches from the prediction table for the specified grid cells, limiting to one patch per grid cell.

### 2.3. Assign & Reassign Ground Truth Labels

Each time the user assigns labels to patches (e.g., via the patch gallery):

- Upsert the `ground_truth_label` in the ground truth table for specific `patch_id`s as needed.

## 3. DL Operations


### 3.1. Insert New Predictions

Each time a DL worker produces new predictions:

- Append new prediction data to the prediction table with the latest `pred_version`.
- Update the aggregate table by incrementing counts in the corresponding buckets.

### 3.2. Remove Old Predictions

When the prediction table becomes "full," i.e., the total count of rows equals the total number of patches in the dataset:

1. Increment a global value for `pred_version`.
2. Drop partitions of the prediction table where `pred_version` is less than the latest version.

## 4. Prototypes
```{csv-table}
:header-rows: 1
:file: db_prototypes.csv
```