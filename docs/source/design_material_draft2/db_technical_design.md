
# Database Table Schema (Citus Distributed)


## Patch Table (Distributed)
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

### pred_patch_latest (Distributed)
| Column Name    | Data Type | Constraints                     | Description                                      |
|----------------|-----------|---------------------------------|--------------------------------------------------|
| patch_id       | BIGINT    | PRIMARY KEY, SHARD KEY          | Unique identifier for the prediction (matches Patch table). |
| embed_x        | FLOAT     | NOT NULL                        | X coordinate of the embedding.                   |
| embed_y        | FLOAT     | NOT NULL                        | Y coordinate of the embedding.                   |
| grid_cell_i    | SMALLINT  | NOT NULL                        | Row index in the grid.                           |
| grid_cell_j    | SMALLINT  | NOT NULL                        | Column index in the grid.                        |
| event_ts       | TIMESTAMP | NOT NULL                        | Timestamp when the prediction was added.         |
| label_class_id | SMALLINT  | NOT NULL, FOREIGN KEY           | Predicted label class for the patch.             |

### pred_patch_last (Distributed)

Same schema as `pred_patch_latest`.

- **Citus:** Both tables are distributed by `patch_id` and co-located with `patch`.

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


## Confusion Matrix LN Table (Distributed Aggregation Table)
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

### Patch Table (Distributed)
- **has**: Each `Patch` has one or more predictions in both `pred_patch_latest` and `pred_patch_last` tables (all co-located on `patch_id`).

### Label Class Table
- **classifies**: Each `Label Class` classifies one or more `Patches`.
- **classifies**: Each `Label Class` classifies one or more predictions in both `pred_patch_latest` and `pred_patch_last` tables.

### Confusion Matrix LN Table (Distributed)
- **aggregates**: Each row aggregates patch-level data for a given shard, co-located with the relevant patches and predictions.


## Citus Distribution Notes

- All distributed tables (`patch`, `pred_patch_latest`, `pred_patch_last`, and `confusion_matrix_ln`) are sharded and co-located using the same distribution column (`patch_id` for patch/prediction tables, `shard_id` for aggregation).
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
    PATCH {
        SERIAL patch_id PK
        INT patch_uid
        SMALLINT label_class_id FK
        INT image_id FK
        FLOAT working_mag
        BYTEA patch_image
    }
    PRED_PATCH_LATEST {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id FK
    }
    PRED_PATCH_LAST {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id FK
    }
    CONFUSION_MATRIX_LN {
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
    IMAGE ||--o{ PATCH : "contains"
    PATCH ||--o{ PRED_PATCH_LATEST : "has"
    PATCH ||--o{ PRED_PATCH_LAST : "has"
    LABEL_CLASS ||--o{ PATCH : "classifies"
    LABEL_CLASS ||--o{ PRED_PATCH_LATEST : "classifies"
    LABEL_CLASS ||--o{ PRED_PATCH_LAST : "classifies"
    CONFUSION_MATRIX_LN ||--o{ LABEL_CLASS : "references"
```