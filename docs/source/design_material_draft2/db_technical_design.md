# Database Table Schema

## Patch Table
| Column Name    | Data Type  | Constraints                     | Description                                      |
|----------------|------------|---------------------------------|--------------------------------------------------|
| patch_id       | SERIAL     | PRIMARY KEY                    | Unique identifier for the patch.                |
| patch_uid      | INT        | UNIQUE                         | External unique identifier for the patch.       |
| label_class_id | SMALLINT   | NOT NULL, FOREIGN KEY          | Ground truth label for the patch.               |
| image_id       | INT        | NOT NULL, FOREIGN KEY          | Identifier for the image containing the patch.  |
| working_mag    | FLOAT      | NOT NULL                       | Working magnification level of the patch.       |
| patch_image    | BYTEA      | NOT NULL                       | Binary data storing the patch image.            |

## Patch Prediction Table
| Column Name    | Data Type | Constraints                     | Description                                      |
|----------------|-----------|---------------------------------|--------------------------------------------------|
| prediction_id  | SERIAL    | PRIMARY KEY                    | Unique identifier for the prediction.           |
| embed_x        | FLOAT     | NOT NULL                       | X coordinate of the embedding.                  |
| embed_y        | FLOAT     | NOT NULL                       | Y coordinate of the embedding.                  |
| grid_cell_i    | SMALLINT  | NOT NULL                       | Row index in the grid.                          |
| grid_cell_j    | SMALLINT  | NOT NULL                       | Column index in the grid.                       |
| event_ts       | TIMESTAMP | NOT NULL                       | Timestamp when the prediction was added.        |
| label_class_id | SMALLINT  | NOT NULL, FOREIGN KEY          | Predicted label class for the patch.            |

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

## Relationships

### Settings Table
- **configures**: Each `Settings` entry configures one or more `Projects`.

### Project Table
- **includes**: Each `Project` includes one or more `Images`.
- **defines**: Each `Project` defines one or more `Label Classes`.

### Image Table
- **contains**: Each `Image` contains one or more `Patches`.

### Patch Table
- **has**: Each `Patch` has one or more `Patch Predictions`.

### Label Class Table
- **classifies**: Each `Label Class` classifies one or more `Patches`.
- **classifies**: Each `Label Class` classifies one or more `Patch Predictions`.

## Entity-Relationship Diagram

```{mermaid}
erDiagram
    SETTINGS {
        SERIAL setting_id PK
        TEXT setting_key
        TEXT setting_value
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
    PATCH_PREDICTION {
        SERIAL prediction_id PK
        FLOAT embed_x
        FLOAT embed_y
        SMALLINT grid_cell_i
        SMALLINT grid_cell_j
        TIMESTAMP event_ts
        SMALLINT label_class_id FK
    }
    SETTINGS ||--o{ PROJECT : "configures"
    PROJECT ||--o{ IMAGE : "includes"
    PROJECT ||--o{ LABEL_CLASS : "defines"
    IMAGE ||--o{ PATCH : "contains"
    PATCH ||--o{ PATCH_PREDICTION : "has"
    LABEL_CLASS ||--o{ PATCH : "classifies"
    LABEL_CLASS ||--o{ PATCH_PREDICTION : "classifies"
```