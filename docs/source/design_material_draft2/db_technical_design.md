
# Database Table Schema (Citus Distributed)

## project{project_id}_patch Table (Distributed)

> **One unique table per project.** Each project has its own table named `project{project_id}_patch` where `{project_id}` is the integer ID of the project (e.g., `project1_patch`, `project2_patch`).

| Column Name    | Data Type          | Constraints                     | Description                                      |
|----------------|--------------------|---------------------------------|--------------------------------------------------|
| patch_id       | BIGINT             | PRIMARY KEY, SHARD KEY          | Unique identifier for the patch.                 |
| patch_uid      | UUID               |                                 | External identifier for the patch.               |
| label_class_id | SMALLINT           | NOT NULL                        | Ground truth label for the patch.                |
| image_id       | INT                | NOT NULL                        | Identifier for the image containing the patch.   |
| downsample_factor | FLOAT              | NOT NULL                        | Factor (>1) at which the patch was downsampled from the base magnification of the underlying image. |
| centroid_x     | FLOAT              |                                 | X pixel coordinate of the patch centroid at base magnification (optional). |
| centroid_y     | FLOAT              |                                 | Y pixel coordinate of the patch centroid at base magnification (optional). |
| polygon        | GEOMETRY(POLYGON)  |                                 | Source polygon geometry (optional, requires PostGIS). |
| patch_image    | BYTEA              | NOT NULL                        | Binary data storing the patch image.             |

> **PostGIS:** The `polygon` column requires the PostGIS extension (`CREATE EXTENSION IF NOT EXISTS postgis CASCADE`). Polygons are written as WKT via `ST_GeomFromText` and read as GeoJSON via `ST_AsGeoJSON`.

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
| label_class_id | SMALLINT  | NOT NULL                        | Predicted label class for the patch.             |

### project{project_id}_pred_patch_last (Distributed)

Same schema as `project{project_id}_pred_patch_latest`.

- **Citus:** Both tables are distributed by `patch_id` and co-located with `project{project_id}_patch`.

## Image Table
| Column Name       | Data Type  | Constraints                     | Description                                      |
|-------------------|------------|---------------------------------|--------------------------------------------------|
| image_id          | SERIAL     | PRIMARY KEY, INDEXED            | Internal unique identifier for the image.        |
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
| Column Name   | Data Type | Constraints                     | Description                                              |
|---------------|-----------|----------------------------------|----------------------------------------------------------|
| project_id    | SERIAL    | PRIMARY KEY, INDEXED            | Internal unique identifier for the project.             |
| project_name  | TEXT      | NOT NULL                        |                                                          |
| description   | TEXT      |                                 |                                                          |

## Label Class Table
| Column Name      | Data Type  | Constraints                     | Description                                      |
|------------------|------------|---------------------------------|--------------------------------------------------|
| label_class_id   | INT        | PRIMARY KEY (with project_id)   | Per-project class ID, allocated sequentially from 0. Equals the model output index. |
| project_id       | INT        | PRIMARY KEY (with label_class_id), NOT NULL, FOREIGN KEY | Identifier for the owning project. |
| name           | TEXT       | NOT NULL, UNIQUE WITHIN PROJECT| Name of the label class.                        |
| color_code     | TEXT       |                                 | Color associated with the label class.          |
| event_ts       | TIMESTAMP  | NOT NULL                       | Timestamp when the label class was created or last updated. |
| is_deleted     | BOOLEAN    | NOT NULL, DEFAULT FALSE         | Soft-delete flag. Deleting a class sets it to `TRUE`; the row is never removed, so IDs are never reused. |

**Label index semantics**

- The primary key is `(label_class_id, project_id)`, so IDs are scoped to a project and every project starts at 0.
- `label_class_id` *is* the model output index; there is no ID-to-index map. The model output dimension is `max(label_class_id) + 1` over the non-UNASSIGNED classes.
- Every project has a reserved `unassigned` class with `label_class_id = -1`, inserted in the same transaction as the project by `ProjectStore.create`. The model has no output slot for it, so it must never index model output (`-1` would silently wrap to the last class in NumPy/PyTorch); mask it out first.
- IDs are assigned by the `label_class_assign_id` BEFORE INSERT trigger as `max(existing id) + 1` per project, serialized with a per-project advisory lock. Callers cannot supply an ID (the only accepted explicit value is `-1`, used for the UNASSIGNED row), so allocation cannot be bypassed.
- Names are unique among non-deleted classes of a project (partial unique index), so a name can be reused after its class is deleted.
- Tables that reference `label_class_id` (`projectN_patch`, `projectN_pred_patch_*`, confusion matrix tables) are scoped to a project by table name and intentionally have no foreign key to `label_class`.
- **Soft delete:** deleted classes keep their row and output slot, so the model output dimension is computed including deleted classes.
- Existing databases are migrated with the notebook `patchsorter/helper_scripts/migrate_label_class_project_scope.ipynb` (dry-run by default, with PASS/FAIL verification).

## Settings Table

The `settings` table stores **only overridden values**. Default values, types, allowed values, and disabled status are defined in `patchsorter/config/settings_defaults.toml` and loaded at runtime. A row exists in the database only when a setting's value differs from its schema default.

| Column Name    | Data Type | Constraints                                           | Description                                      |
|----------------|-----------|-------------------------------------------------------|--------------------------------------------------|
| override_id    | SERIAL    | PRIMARY KEY, AUTOINCREMENT                            | Internal unique identifier for the override row. |
| project_id     | INT       | FOREIGN KEY, NULLABLE                                 | Identifier for the associated project. `NULL` means the setting applies at the application level. |
| setting_key    | TEXT      | NOT NULL                                              | Key for the setting.                            |
| value          | TEXT      | NOT NULL                                              | The overridden value (stored as raw string).    |
| updated_at     | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP                   | Timestamp of the last update.                   |

Constraints:
- `UNIQUE (project_id, setting_key)` — one row per setting per scope.
- Partial unique index `uq_app_settings` on `setting_key` WHERE `project_id IS NULL` — ensures a single application-level row per key.

Default values for all settings are loaded from `patchsorter/config/settings_defaults.toml` at runtime. Each entry in that file carries a `scope` field (`"application"` or `"project"`) that determines whether the setting is resolved with `project_id = NULL` (application-level) or per project.


## Code Conventions

### Table Name Helpers

All per-project table names are constructed via static methods on the store classes — the single source of truth for naming conventions:

| Static Method | Returns |
|---|---|
| `PatchStore.build_table_name(project_id)` | `project{N}_patch` |
| `PatchStore.build_pred_table_name(project_id, suffix)` | `project{N}_pred_patch_{suffix}` |
| `ConfusionMatrixStore.build_table_name(project_id, level)` | `project{N}_confusion_matrix_l{level}` |

All stores, ORM model factories, and schema management code call these static methods directly rather than constructing names ad hoc.

### Constants (`patchsorter/config/constants.py`)

Shared `StrEnum` types used throughout the codebase:

| Enum | Members | Used for |
|---|---|---|
| `PredPatchSuffix` | `LATEST = "latest"`, `LAST = "last"` | Selecting between the two pred-patch tables |
| `SettingType` | `ENUM`, `STRING`, `BOOLEAN`, `INTEGER` | Typing the `setting_type` column; drives CHECK constraint generation in the ORM model |

### ORM Models (`patchsorter/db/head_client/models.py`)

All reference tables (`project`, `image`, `label_class`, `settings`, `log`) are defined as SQLAlchemy ORM classes extending `Base`.  Per-project distributed tables are created on demand via factory functions:

| Factory | Model class name | Table |
|---|---|---|
| `patch_model(project_id)` | `Patch{N}` | `project{N}_patch` |
| `pred_patch_model(project_id, suffix)` | `PredPatch{Latest\|Last}{N}` | `project{N}_pred_patch_{suffix}` |
| `confusion_matrix_model(project_id, level)` | `ConfusionMatrix{N}L{level}` | `project{N}_confusion_matrix_l{level}` |
| `all_project_models(project_id)` | — | All seven per-project tables |

Factory results are cached per `(project_id[, level])` to prevent duplicate mapper registrations in `Base.metadata`.

The `SettingOverride` model maps to the `settings` table and stores only per-project or application-level value overrides. Default values, types, allowed values, and disabled status are loaded from `patchsorter/config/settings_defaults.toml` at runtime via `SettingsStore._load_settings_schema()`.


## Log Table
| Column Name | Data Type | Constraints                | Description                                          |
|-------------|-----------|----------------------------|------------------------------------------------------|
| id          | INTEGER   | PRIMARY KEY, AUTOINCREMENT | Internal unique identifier for the log entry.        |
| name        | TEXT      | NOT NULL                   | Name or source associated with the log entry.        |
| timestamp   | DATETIME  | NOT NULL                   | Timestamp when the log entry was recorded.           |
| level       | ENUM      | NOT NULL, DEFAULT 'INFO'   | Severity level of the log entry (e.g. INFO, WARNING, ERROR). |
| message     | TEXT      | NOT NULL, DEFAULT ''       | Log message content.                                 |


## project{project_id}_confusion_matrix_ln Table (Distributed Aggregation Table)

> **One unique table per project.** Each project has its own confusion matrix table named `project{project_id}_confusion_matrix_ln` where `{project_id}` is the integer ID of the project (e.g., `project1_confusion_matrix_ln`, `project2_confusion_matrix_ln`).

| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| shard_id       | BIGINT     | SHARD KEY, NOT NULL             | Shard identifier for co-location.                |
| grid_cell_i    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Row index in the grid.                          |
| grid_cell_j    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Column index in the grid.                       |
| bucket_date    | DATE       | NOT NULL                        | Date when the bucket was last updated.           |
| pred_label     | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Predicted label for the bucket.                 |
| gt_label       | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Ground truth label for the bucket.              |
| count          | INT        | NOT NULL                        | Number of patches in the bucket.                 |

- **Citus:** Distributed by `shard_id` and co-located with the patch tables. `shard_id` should be derived from `patch_id` to ensure co-location.


## Relationships

### Settings Table
- **configures**: Each `settings` row configures a single project unless `project_id` is null, in which case it applies at the application level. Only overridden values are stored; defaults are loaded from `patchsorter/config/settings_defaults.toml`.

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

### Log Table
- **records**: Each `Log` entry records an application-level event. Not associated with any project.


## Citus Distribution Notes

- All distributed tables (`project{project_id}_patch`, `project{project_id}_pred_patch_latest`, `project{project_id}_pred_patch_last`, and `project{project_id}_confusion_matrix_ln`) are sharded and co-located using the same distribution column (`patch_id` for patch/prediction tables, `shard_id` for aggregation). Each project has its own set of these tables.
- The `shard_id` in the aggregation table should be derived from `patch_id` (e.g., using the same hash function or mapping) to ensure co-location.
- Co-location ensures efficient distributed joins and aggregations.

## Deletion Protocols

### Deleting an Annotation (Label) Class

The "Unlabeled" class (`label_class_id = -1`, one per project) is a reserved default and **cannot be deleted**.

1. **Reset patch ground truth labels.** `UPDATE projectN_patch SET label_class_id = -1 WHERE label_class_id = $deleted_id` across all shards.
2. **Reset prediction labels.** `UPDATE projectN_pred_patch_latest SET label_class_id = -1 WHERE label_class_id = $deleted_id` and the same for `projectN_pred_patch_last`.
3. **Reset confusion matrix references.** `UPDATE projectN_confusion_matrix_ln SET pred_label = -1 WHERE pred_label = $deleted_id` and the same for `gt_label`.
4. **Soft-delete the label class row.** `UPDATE label_class SET is_deleted = TRUE WHERE label_class_id = $deleted_id AND project_id = $project_id`.

Steps 1–3 must complete successfully before step 4 is executed. All steps should be wrapped in a single transaction where possible.

### Deleting an Image

1. **Reset patch ground truth labels to "Unlabeled".** `UPDATE projectN_patch SET label_class_id = -1 WHERE image_id = $deleted_image_id`.
2. **Delete predictions for the image's patches.** `DELETE FROM projectN_pred_patch_latest WHERE patch_id IN (SELECT patch_id FROM projectN_patch WHERE image_id = $deleted_image_id)` and the same for `projectN_pred_patch_last`.
3. **Delete the patches.** `DELETE FROM projectN_patch WHERE image_id = $deleted_image_id`.
4. **Delete the image row.** `DELETE FROM image WHERE image_id = $deleted_image_id`.

Steps 1–3 must complete before step 4. All steps should be wrapped in a single transaction.

### Deleting a Project

Deleting a project removes all associated data. This is a destructive, irreversible operation.

1. **Drop the project's distributed tables.** `DROP TABLE projectN_patch, projectN_pred_patch_latest, projectN_pred_patch_last, projectN_confusion_matrix_ln CASCADE`. Dropping these tables implicitly removes all patches, predictions, and aggregations.
2. **Delete label classes.** `DELETE FROM label_class WHERE project_id = $deleted_project_id`.
3. **Delete images.** `DELETE FROM image WHERE project_id = $deleted_project_id`.
4. **Delete settings.** `DELETE FROM settings WHERE project_id = $deleted_project_id`.
5. **Delete the project row.** `DELETE FROM project WHERE project_id = $deleted_project_id`.

Steps 1–4 must complete before step 5.

---

## Entity-Relationship Diagram (Citus Focus)

```{mermaid}
erDiagram
    SETTINGS {
        SERIAL  override_id PK
        INT     project_id FK
        TEXT    setting_key
        TEXT    value
        TIMESTAMP updated_at
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
        INT label_class_id PK
        INT project_id PK
        TEXT name
        TEXT color_code
        TIMESTAMP event_ts
        BOOLEAN is_deleted
    }
    projectN_patch {
        SERIAL patch_id PK
        INT patch_uid
        SMALLINT label_class_id
        INT image_id
        FLOAT downsample_factor
        FLOAT centroid_x
        FLOAT centroid_y
        GEOMETRY polygon
        BYTEA patch_image
    }
    projectN_pred_patch_latest {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id
    }
    projectN_pred_patch_last {
        SERIAL patch_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id
    }
    projectN_confusion_matrix_ln {
        SMALLINT grid_cell_i PK
        SMALLINT grid_cell_j PK
        DATE bucket_date
        SMALLINT pred_label
        SMALLINT gt_label
        INT count
    }
    LOG {
        INTEGER id PK
        TEXT name
        DATETIME timestamp
        ENUM level
        TEXT message
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