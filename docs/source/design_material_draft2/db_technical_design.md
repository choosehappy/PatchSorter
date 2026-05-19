
# Database Table Schema (Citus Distributed)


## project{project_id}_patch Table (Distributed)

> **One unique table per project.** Each project has its own table named `project{project_id}_patch` where `{project_id}` is the integer ID of the project (e.g., `project1_patch`, `project2_patch`).

| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| patch_id       | BIGINT     | PRIMARY KEY, SHARD KEY          | Unique identifier for the patch.                 |
| patch_uid      | INT        | UNIQUE                          | External unique identifier for the patch.        |
| label_class_id | SMALLINT   | NOT NULL, FOREIGN KEY           | Ground truth label for the patch.                |
| image_id       | INT        | NOT NULL, FOREIGN KEY           | Identifier for the image containing the patch.   |
| working_mag    | FLOAT      | NOT NULL                        | Working magnification level of the patch.        |
| patch_image    | BYTEA      | NOT NULL                        | Binary data storing the patch image.             |

- **Citus:** Distributed by `patch_id` and co-located with prediction and aggregation tables.


## Patch Prediction Tables (Distributed)

Two tables are used for patch predictions:

> **One unique pair of tables per project.** Each project has its own prediction tables named `project{project_id}_pred_patch_latest` and `project{project_id}_pred_patch_last` where `{project_id}` is the integer ID of the project (e.g., `project1_pred_patch_latest`, `project1_pred_patch_last`).

### project{project_id}_pred_patch_latest (Distributed)
| Column Name    | Data Type | Constraints                     | Description                                      |
|----------------|-----------|---------------------------------|--------------------------------------------------|
| patch_id       | BIGINT    | PRIMARY KEY, SHARD KEY          | Unique identifier for the prediction (matches Patch table). |
| embed_x        | FLOAT     | NOT NULL                        | X coordinate of the embedding.                   |
| embed_y        | FLOAT     | NOT NULL                        | Y coordinate of the embedding.                   |
| grid_cell_i    | SMALLINT  | NOT NULL                        | Row index in the grid.                           |
| grid_cell_j    | SMALLINT  | NOT NULL                        | Column index in the grid.                        |
| event_ts       | TIMESTAMP | NOT NULL                        | Timestamp when the prediction was added.         |
| label_class_id | SMALLINT  | NOT NULL, FOREIGN KEY           | Predicted label class for the patch.             |

### project{project_id}_pred_patch_last (Distributed)

Same schema as `project{project_id}_pred_patch_latest`.

- **Citus:** Both tables are distributed by `patch_id` and co-located with `project{project_id}_patch`.

## Image Table
| Column Name       | Data Type  | Constraints                     | Description                                      |
|-------------------|------------|---------------------------------|--------------------------------------------------|
| image_id          | SERIAL     | PRIMARY KEY                    | Unique identifier for the image.                |
| project_id        | INT        | NOT NULL, FOREIGN KEY          | Identifier for the associated project.          |
| name              | TEXT       | NOT NULL, UNIQUE WITHIN PROJECT| Name of the image.                              |
| image_path        | TEXT       | NOT NULL                       | File path or URI of the image.                  |
| upload_ts         | TIMESTAMP  | NOT NULL                       | Timestamp when the image was uploaded.          |
| base_mag          | FLOAT      | NOT NULL                       | Base magnification level of the image.          |
| base_width        | INT        | NOT NULL                       | Width of the image at base magnification.       |
| base_height       | INT        | NOT NULL                       | Height of the image at base magnification.      |
| deepzoom_tilesize | INT        | NOT NULL                       | Tile size used in DeepZoom format.              |
| embedding_x       | FLOAT      |                                 | X coordinate of the image embedding (optional). |
| embedding_y       | FLOAT      |                                 | Y coordinate of the image embedding (optional). |
| group_id          | INT        |                                 | Group ID from CohortFinder.                     |
| train_test_split  | INT        |                                 | Train/test split from CohortFinder.             |

## Project Table
| Column Name   | Data Type | Constraints                     |
|---------------|-----------|---------------------------------|
| project_id    | SERIAL    | PRIMARY KEY                    |
| project_name  | TEXT      | NOT NULL                       |
| description   | TEXT      |                                 |

## Label Class Table
| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| label_class_id | SERIAL     | PRIMARY KEY                    | Unique identifier for the label class.          |
| project_id     | INT        | NOT NULL, FOREIGN KEY          | Identifier for the associated project.          |
| name           | TEXT       | NOT NULL, UNIQUE WITHIN PROJECT| Name of the label class.                        |
| color_code     | TEXT       |                                 | Color associated with the label class.          |
| event_ts       | TIMESTAMP  | NOT NULL                       | Timestamp when the label class was created or last updated. |

## Settings Table
| Column Name   | Data Type | Constraints                     | Description                                      |
|---------------|-----------|---------------------------------|--------------------------------------------------|
| setting_id    | SERIAL    | PRIMARY KEY                    | Unique identifier for the setting.              |
| project_id    | INT       | FOREIGN KEY, NULLABLE          | Identifier for the associated project. Null if the setting applies at the application level. |
| setting_key   | TEXT      | NOT NULL                       | Key for the setting.                            |
| setting_value | TEXT      | NOT NULL                       | Value for the setting.                          |
| disabled      | BOOLEAN   | DEFAULT FALSE                  | Flag indicating if the setting is disabled and should not be updated. |


## project{project_id}_confusion_matrix_ln Table (Distributed Aggregation Table)

> **One unique table per project.** Each project has its own confusion matrix table named `project{project_id}_confusion_matrix_ln` where `{project_id}` is the integer ID of the project (e.g., `project1_confusion_matrix_ln`, `project2_confusion_matrix_ln`).

| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| shard_id       | BIGINT     | SHARD KEY, NOT NULL             | Shard identifier for co-location.                |
| grid_cell_i    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Row index in the grid.                          |
| grid_cell_j    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Column index in the grid.                       |
| bucket_date    | DATE       | NOT NULL                        | Date when the bucket was last updated.           |
| pred_label     | SMALLINT   | NOT NULL, FOREIGN KEY, PRIMARY KEY (composite)| Predicted label for the bucket.                 |
| gt_label       | SMALLINT   | NOT NULL, FOREIGN KEY, PRIMARY KEY (composite)| Ground truth label for the bucket.              |
| count          | INT        | NOT NULL                        | Number of patches in the bucket.                 |

- **Citus:** Distributed by `shard_id` and co-located with the patch tables. `shard_id` should be derived from `patch_id` to ensure co-location.


## Relationships

### Settings Table
- **configures**: Each `Settings` entry configures a single project unless `project_id` is null, in which case it applies at the application level.

### Project Table
- **includes**: Each `Project` includes one or more `Images`.
- **defines**: Each `Project` defines one or more `Label Classes`.

### Image Table
- **contains**: Each `Image` contains one or more `Patches`.

### project{project_id}_patch Table (Distributed)
- **has**: Each `Patch` has one or more predictions in both `project{project_id}_pred_patch_latest` and `project{project_id}_pred_patch_last` tables (all co-located on `patch_id`).

### Label Class Table
- **classifies**: Each `Label Class` classifies one or more `Patches`.
- **classifies**: Each `Label Class` classifies one or more predictions in both `project{project_id}_pred_patch_latest` and `project{project_id}_pred_patch_last` tables.

### project{project_id}_confusion_matrix_ln Table (Distributed)
- **aggregates**: Each row aggregates patch-level data for a given shard, co-located with the relevant patches and predictions.


## Citus Distribution Notes

- All distributed tables (`project{project_id}_patch`, `project{project_id}_pred_patch_latest`, `project{project_id}_pred_patch_last`, and `project{project_id}_confusion_matrix_ln`) are sharded and co-located using the same distribution column (`patch_id` for patch/prediction tables, `shard_id` for aggregation). Each project has its own set of these tables.
- The `shard_id` in the aggregation table should be derived from `patch_id` (e.g., using the same hash function or mapping) to ensure co-location.
- Co-location ensures efficient distributed joins and aggregations.

## Entity-Relationship Diagram (Citus Focus)

```{mermaid}
erDiagram
    SETTINGS {
        SERIAL setting_id PK
        INT project_id FK
        TEXT setting_key
        TEXT setting_value
        BOOLEAN disabled
    }
    PROJECT {
        SERIAL project_id PK
        TEXT project_name
        TEXT description
    }
    IMAGE {
        SERIAL image_id PK
        INT project_id FK
        TEXT name
        TEXT image_path
        TIMESTAMP upload_ts
        FLOAT base_mag
        INT base_width
        INT base_height
        INT deepzoom_tilesize
        FLOAT embedding_x
        FLOAT embedding_y
        INT group_id
        INT train_test_split
    }
    LABEL_CLASS {
        SERIAL label_class_id PK
        INT project_id FK
        TEXT name
        TEXT color_code
        TIMESTAMP event_ts
    }
    projectN_patch {
        SERIAL patch_id PK
        INT patch_uid
        SMALLINT label_class_id FK
        INT image_id FK
        FLOAT working_mag
        BYTEA patch_image
    }
    projectN_pred_patch_latest {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id FK
    }
    projectN_pred_patch_last {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id FK
    }
    projectN_confusion_matrix_ln {
        SMALLINT grid_cell_i PK
        SMALLINT grid_cell_j PK
        DATE bucket_date
        SMALLINT pred_label FK
        SMALLINT gt_label FK
        INT count
    }

    SETTINGS ||--|| PROJECT : "configures"
    PROJECT ||--o{ IMAGE : "includes"
    PROJECT ||--o{ LABEL_CLASS : "defines"
    IMAGE ||--o{ projectN_patch : "contains"
    projectN_patch ||--o{ projectN_pred_patch_latest : "has"
    projectN_patch ||--o{ projectN_pred_patch_last : "has"
    LABEL_CLASS ||--o{ projectN_patch : "classifies"
    LABEL_CLASS ||--o{ projectN_pred_patch_latest : "classifies"
    LABEL_CLASS ||--o{ projectN_pred_patch_last : "classifies"
    projectN_confusion_matrix_ln ||--o{ LABEL_CLASS : "references"
```