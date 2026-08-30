
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
| label_class_id   | SERIAL     | PRIMARY KEY, INDEXED            | Internal unique identifier for the label class.  |
| project_id       | INT        | NOT NULL, FOREIGN KEY          | Identifier for the associated project.          |
| name           | TEXT       | NOT NULL, UNIQUE WITHIN PROJECT| Name of the label class.                        |
| color_code     | TEXT       |                                 | Color associated with the label class.          |
| event_ts       | TIMESTAMP  | NOT NULL                       | Timestamp when the label class was created or last updated. |

## Settings Table
| Column Name    | Data Type | Constraints                                           | Description                                      |
|----------------|-----------|-------------------------------------------------------|--------------------------------------------------|
| setting_id     | SERIAL    | PRIMARY KEY, INDEXED                                  | Internal unique identifier for the setting.      |
| project_id     | INT       | FOREIGN KEY, NULLABLE                                 | Identifier for the associated project. Null if the setting applies at the application level. |
| setting_key    | TEXT      | NOT NULL                                              | Key for the setting.                            |
| setting_value  | TEXT      | NOT NULL                                              | Current value for the setting.                  |
| default_value  | TEXT      | NOT NULL                                              | Default value used when the setting is reset.   |
| setting_type   | TEXT      | NOT NULL, CHECK IN ('enum','string','boolean','integer') | Data type of the setting value. Values are defined by `SettingType` in `patchsorter/config/constants.py`. |
| allowed_values | TEXT      | NULLABLE, REQUIRED when setting_type = 'enum'        | Allowed values for enum settings.               |
| disabled       | BOOLEAN   | NOT NULL, DEFAULT FALSE                               | When true, the setting is read-only and cannot be updated after the initial insert. |

Constraints:
- `UNIQUE (project_id, setting_key)` — one row per setting per scope.
- `CHECK (setting_type != 'enum' OR allowed_values IS NOT NULL)` — enum settings must declare their allowed values.

Default values for all settings are seeded from `patchsorter/config/settings_defaults.toml`.  Each entry in that file carries a `scope` field (`"application"` or `"project"`) that determines whether the setting is stored with `project_id = NULL` (application-level) or per project.


## Log Table
| Column Name | Data Type | Constraints                | Description                                          |
|-------------|-----------|----------------------------|------------------------------------------------------|
| id          | INTEGER   | PRIMARY KEY, AUTOINCREMENT | Internal unique identifier for the log entry.        |
| name        | TEXT      | NOT NULL                   | Name or source associated with the log entry.        |
| timestamp   | TIMESTAMP | NOT NULL                   | Timestamp when the log entry was recorded.           |
| level       | TEXT      | NOT NULL, DEFAULT 'INFO'   | Severity level of the log entry (e.g. INFO, WARNING, ERROR). |
| message     | TEXT      | NOT NULL, DEFAULT ''       | Log message content.                                 |

## Confusion Matrix Tables (Distributed Aggregation)

> **Five unique tables per project.** Each project has five confusion matrix tables named `project{project_id}_confusion_matrix_l8` through `project{project_id}_confusion_matrix_l12` where `{project_id}` is the integer ID of the project. Each level stores aggregated counts at a different hierarchical grid resolution.

| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| shard_id       | BIGINT     | PRIMARY KEY, SHARD KEY, NOT NULL             | Shard identifier for co-location.                |
| grid_cell_i    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Row index in the grid.                          |
| grid_cell_j    | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Column index in the grid.                       |
| bucket_date    | DATE       | NOT NULL                        | Date when the bucket was last updated.           |
| pred_label     | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Predicted label for the bucket.                 |
| gt_label       | SMALLINT   | NOT NULL, PRIMARY KEY (composite)| Ground truth label for the bucket.              |
| count          | INT        | NOT NULL                        | Number of patches in the bucket.                 |

- **Citus:** Distributed by `shard_id` and co-located with the patch tables. `shard_id` is derived from the colocated `patch_id` via the `CitusShardMap` mapping.
- **Hierarchical resolution:** l12 stores raw (finest-level) grid cell counts; each coarser level (l11, l10, l9, l8) right-shifts `grid_cell_i`/`grid_cell_j` by one additional bit relative to l12.

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

### Confusion Matrix Tables
- **aggregates**: Each row aggregates patch-level data for a given shard, co-located with the relevant patches and predictions. Five levels (l8–l12) provide hierarchical grid resolution.

### Log Table
- **records**: Each `Log` entry records an application-level event. Not associated with any project.


## Citus Distribution Notes

- All distributed tables (`project{project_id}_patch`, `project{project_id}_pred_patch_latest`, `project{project_id}_pred_patch_last`, and `project{project_id}_confusion_matrix_l8` through `l12`) are sharded and co-located using the same distribution column (`patch_id` for patch/prediction tables, `shard_id` for aggregation). Each project has its own set of these tables.
- The `shard_id` in the aggregation table should be derived from `patch_id` (e.g., using the same hash function or mapping) to ensure co-location.
- Co-location ensures efficient distributed joins and aggregations.
- Reference tables (`project`, `image`, `label_class`, `settings`, `log`) are distributed via `create_reference_table()`, meaning every worker holds a full copy.

## Deletion Protocols

### Deleting an Annotation (Label) Class

The "Unlabeled" class (`label_class_id = 1`) is a reserved default and **cannot be deleted**.

1. **Reset patch ground truth labels.** `UPDATE projectN_patch SET label_class_id = 1 WHERE label_class_id = $deleted_id` across all shards.
2. **Reset prediction labels.** `UPDATE projectN_pred_patch_latest SET label_class_id = 1 WHERE label_class_id = $deleted_id` and the same for `projectN_pred_patch_last`.
3. **Reset confusion matrix references.** `UPDATE projectN_confusion_matrix_l{lvl} SET pred_label = 1 WHERE pred_label = $deleted_id` and the same for `gt_label` (for each level l8–l12).
4. **Delete the label class row.** `DELETE FROM label_class WHERE label_class_id = $deleted_id`.

Steps 1–3 must complete successfully before step 4 is executed. All steps should be wrapped in a single transaction where possible.

### Deleting an Image

1. **Reset patch ground truth labels to "Unlabeled".** `UPDATE projectN_patch SET label_class_id = 1 WHERE image_id = $deleted_image_id`.
2. **Delete predictions for the image's patches.** `DELETE FROM projectN_pred_patch_latest WHERE patch_id IN (SELECT patch_id FROM projectN_patch WHERE image_id = $deleted_image_id)` and the same for `projectN_pred_patch_last`.
3. **Delete the patches.** `DELETE FROM projectN_patch WHERE image_id = $deleted_image_id`.
4. **Delete the image row.** `DELETE FROM image WHERE image_id = $deleted_image_id`.

Steps 1–3 must complete before step 4. All steps should be wrapped in a single transaction.

### Deleting a Project

Deleting a project removes all associated data. This is a destructive, irreversible operation.

1. **Drop the project's distributed tables.** `DROP TABLE projectN_patch, projectN_pred_patch_latest, projectN_pred_patch_last, projectN_confusion_matrix_l8, projectN_confusion_matrix_l9, projectN_confusion_matrix_l10, projectN_confusion_matrix_l11, projectN_confusion_matrix_l12 CASCADE`. Dropping these tables implicitly removes all patches, predictions, and aggregations.
2. **Delete label classes.** `DELETE FROM label_class WHERE project_id = $deleted_project_id`.
3. **Delete images.** `DELETE FROM image WHERE project_id = $deleted_project_id`.
4. **Delete settings.** `DELETE FROM settings WHERE project_id = $deleted_project_id`.
5. **Delete the project row.** `DELETE FROM project WHERE project_id = $deleted_project_id`.

Steps 1–4 must complete before step 5.

---

## Code Conventions

### Table Name Helpers

All per-project table names are constructed via static methods on the store classes — the single source of truth for naming conventions:

| Static Method | Returns |
|---|---|
| `PatchStore.build_table_name(project_id)` | `project{N}_patch` |
| `PatchStore.build_table_name(project_id, shard_id)` | `project{N}_patch_{shard_id}` (physical shard table) |
| `PatchStore.build_pred_table_name(project_id, suffix)` | `project{N}_pred_patch_{suffix}` |
| `PatchStore.build_pred_table_name(project_id, suffix, shard_id)` | `project{N}_pred_patch_{suffix}_{shard_id}` (physical shard table) |
| `ConfusionMatrixStore.build_table_name(project_id, level)` | `project{N}_confusion_matrix_l{level}` |
| `ConfusionMatrixStore.build_table_name(project_id, level, shard_id)` | `project{N}_confusion_matrix_l{level}_{shard_id}` (physical shard table) |

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

## Distributed Infrastructure

### CitusShardMap (`patchsorter/db/head_client/database_manager.py`)

Maps colocated shard pairs between the patch table and the `pred_patch_latest` table by querying `pg_dist_shard`:

```sql
SELECT s1.shardid AS shard_a, s2.shardid AS shard_b
FROM pg_dist_shard s1
JOIN pg_dist_shard s2 ON s1.shardminvalue = s2.shardminvalue
                     AND s1.shardmaxvalue = s2.shardmaxvalue
JOIN pg_dist_partition p1 ON s1.logicalrelid = p1.logicalrelid
JOIN pg_dist_partition p2 ON s2.logicalrelid = p2.logicalrelid
WHERE s1.logicalrelid = '{table_a}'::regclass
  AND s2.logicalrelid = '{table_b}'::regclass
  AND p1.colocationid = p2.colocationid;
```

Returns `{shard_id_a: shard_id_b}` dict. Key methods:

| Method | Returns |
|---|---|
| `get_table_a_shard_list()` | All shard IDs for the patch table |
| `get_table_b_shard_list()` | All shard IDs for `pred_patch_latest` |
| `get_b_shard_for_a_shard(shard_a)` | Colocated pred_patch shard ID for a given patch shard |

### DatabaseManager (`patchsorter/db/head_client/database_manager.py`)

Schema and DDL manager providing project lifecycle and table rotation:

| Method | Description |
|---|---|
| `get_worker_nodes()` | Query active Citus worker nodes via `citus_get_active_worker_nodes()`. |
| `register_project_models()` | Query all existing project IDs and register their per-project ORM models with `Base.metadata`. |
| `drop_all_tables()` | Drop base tables via ORM, then drop all `project%_%` tables via raw SQL. |
| `setup_schema()` | Create all tables/extensions, seed the "unassigned" label class, distribute reference tables, seed app settings. |
| `create_project_tables(project_id, conn)` | Create per-project `project{N}_patch`, `project{N}_pred_patch_latest`, `project{N}_pred_patch_last`, and `project{N}_confusion_matrix_l8`–`l12`; distribute them; create indexes. |
| `setup_triggers(project_id, raw_conn)` | Install statement-level triggers for confusion matrix maintenance (see below). |
| `setup_project(project_id)` | Atomic wrapper: creates tables → commits → installs triggers → commits. Sets `citus.multi_shard_modify_mode = 'sequential'`. |
| `rotate_pred_patch_tables(project_id)` | 3-way rename: `TRUNCATE last → tmp`, `latest → last`, `tmp → latest`. No rows copied, no tables created/dropped. |
| `get_shard_map_for_patch_and_pred(project_id)` | Return a `CitusShardMap` for the colocated patch and pred_patch_latest tables. |
| `clear_predictions(project_id)` | Truncate both pred_patch tables and all five confusion matrix tables. |

### Triggers for Confusion Matrix Maintenance

Two trigger functions maintain five confusion matrix tables (l8–l12) in lock-step:

**Trigger A — AFTER INSERT on `project{N}_pred_patch` shards:**
- Joins new prediction rows with the colocated patch shard to obtain `gt_label`.
- Upserts aggregated counts into all five colocated CM shards in a single loop.
- For each level, right-shifts `grid_cell_i`/`grid_cell_j` by `(12 - level)` bits.
- Resolves CM shards dynamically from `pg_dist_shard` using the shard's `shardminvalue`.
- Removes rows whose count reaches zero or below.

**Trigger B — AFTER UPDATE on `project{N}_patch` shards:**
- Detects `gt_label` changes via `old_rows`/`new_rows` transition tables.
- Computes net deltas against both `pred_patch_latest` and `pred_patch_last` for the changed patches.
- Upserts deltas into all five CM shards at each level.
- Resolves CM shards dynamically from `pg_dist_shard`.
- Removes rows whose count reaches zero or below.

Both trigger functions use `SET LOCAL enable_nestloop = off` to force hash joins against transition tables.

### WorkerPatchStore (`patchsorter/db/worker_client/patch.py`)

Read-only data-access layer for a project's patch and pred_patch shard tables on a worker node:

| Method | Description |
|---|---|
| `fetch_patch_batch(shard_id, after_id, batch_size)` | Fetch a single page of patch rows from a local shard table using keyset pagination on `patch_id`. |
| `fetch_patches_by_shard(shard_id, batch_size)` | Yield batches of patch rows streamed from a single local shard table (excludes `patch_image`). |
| `insert_predictions_to_shard(shard_id, records)` | Insert prediction rows into the local `pred_patch_latest` shard via COPY. Each record is a 7-tuple: `(patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, event_ts, label_class_id)`. |

All methods connect directly to a Citus worker and operate only on the locally placed physical shard tables (e.g., `project{N}_patch_{shard_id}`) via SQLAlchemy Core — no ORM.

---

## Entity-Relationship Diagram (Citus Focus)

```{mermaid}
erDiagram
    SETTINGS {
        SERIAL  setting_id PK
        INT     project_id FK
        TEXT    setting_key
        TEXT    setting_value
        TEXT    default_value
        TEXT    setting_type
        TEXT    allowed_values
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
        SMALLINT pred_label PK
        SMALLINT gt_label PK
        INT count
    }
    LOG {
        INTEGER id PK
        TEXT name
        TIMESTAMP timestamp
        TEXT level
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