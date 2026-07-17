# Implementation Plan: `process_row` Ray Task for Upload Processing

## 1. File System Manager (`patchsorter/api/v1/upload/fsmanager.py`)

### `FileStore` abstract base class
- **Base class** for managing paths with a configurable sub_path
- Constructor: `__init__(self, sub_path: str)`
- Sets `self.base_path = constants.MOUNTS_PATH` (i.e. `/opt/PatchSorter/mounts`)
- Sets `self.full_path = os.path.join(self.base_path, sub_path)`
- **Note**: `constants.py` must be updated to add `MOUNTS_PATH = os.path.join('/opt/PatchSorter', 'mounts')`
- Provides methods:
  - `get_base_path()` — returns `self.base_path` (the mounts root)
  - `get_full_path(filepath=None)` — returns `self.full_path` or `os.path.join(self.full_path, filepath)`
  - `global_to_relative(path)` — converts absolute path to relative (w.r.t. `self.full_path`)
  - `relative_to_global(path)` — converts relative path to absolute (w.r.t. `self.full_path`)

### `NASWriteStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `"nas_write"`
- **Purpose**: PatchSorter writable storage (uploaded files, projects, masks)
- **Methods**:
  - `get_project_path(project_id: int) -> str` — returns absolute path `{full_path}/projects/proj_{project_id}`
  - `get_project_image_path(project_id: int, image_id: int) -> str` — returns absolute path `{full_path}/projects/proj_{project_id}/images/img_{image_id}`
  - `get_project_mask_path(project_id: int, image_id: int) -> str` — returns absolute path `{get_project_image_path(...)}/masks`
  - `get_temp_path() -> str` — returns absolute path `{full_path}/temp`
  - `move_to_permanent(session_id: str, project_id: int, image_id: int, filename: str) -> str` — atomic `shutil.move` from `UploadStore` image path to `get_project_image_path(project_id, image_id)`, creates dest dir if needed, returns the new absolute path

### `NASReadStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `"nas_read"`
- **Purpose**: Read-only folder/CSV uploads mounted to the PatchSorter Docker container (outside of session-managed paths)
- **Methods**:
  - `get_input_images_path() -> str` — returns absolute path `{full_path}/images`
  - `get_input_masks_dir() -> str` — returns absolute path `{full_path}/masks`

### `UploadStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `os.path.join("nas_write", "tmp", "upload_sessions")` (root within nas_write mounts)
- **Purpose**: Per-upload-session temporary storage
- **Methods**:
  - `get_session_dir(session_id: str) -> str` — returns absolute path `{full_path}/{session_id}`
  - `get_images_dir(session_id: str) -> str` — returns absolute path `{full_path}/{session_id}/images`
  - `get_masks_dir(session_id: str) -> str` — returns absolute path `{full_path}/{session_id}/masks`
  - `get_patch_csvs_dir(session_id: str) -> str` — returns absolute path `{full_path}/{session_id}/patch_csvs`
  - `get_image_path(session_id: str, filename: str) -> str` — returns `{get_images_dir(session_id)}/{filename}`
  - `get_mask_path(session_id: str, filename: str) -> str` — returns `{get_masks_dir(session_id)}/{filename}`
  - `get_patch_csv_path(session_id: str, filename: str) -> str` — returns `{get_patch_csvs_dir(session_id)}/{filename}`
  - `create_session_dirs(session_id: str)` — creates `images/`, `masks/`, `patch_csvs/` subdirs under the session dir
  - `cleanup_session(session_id: str)` — removes the session directory via `shutil.rmtree`

### `FileStoreManager` class
- **Constructor**: `__init__(self)`
- **Purpose**: Lightweight container for the three store instances. Has no methods of its own — all path logic lives in the stores.
- **Attributes**:
  - `self.nas_write = NASWriteStore()`
  - `self.nas_read = NASReadStore()`
  - `self.upload = UploadStore()`

### Path structure

```
nas_write/
├── tmp/
│   └── upload_sessions/
│       └── {session_id}/
│           ├── images/
│           ├── masks/
│           └── patch_csvs/
└── projects/
    └── proj_{project_id}/
        └── images/
            └── img_{image_id}/
                └── {image_filename}
                └── masks/

nas_read/
├── images/
└── masks/
```

---

## 2. Patch Extraction Utilities (`patchsorter/utils/patch_extraction.py`)

### Constants
- **`BASE_MAG_PPM_MICRONS = 0.25`** — microns per pixel at 40x base magnification
- **`MAG_TO_PPM_FACTOR = 10.0`** — derived from `BASE_MAG_PPM_MICRONS * BASE_MAG` (10.0 = 0.25 * 40)
- Helper: `mm_per_pixel_at_base(base_mag) -> float` returns `(MAG_TO_PPM_FACTOR / base_mag) / 1000`

### Deprecated section
- Mark existing `_open_ogr_datasource`, `_extract_patch_region`, and `_makepatch_geojson` as deprecated with a `@deprecated` decorator and a comment pointing to the new upload processing flow

### New: `compute_downsample_factor` function
- **Signature**: `compute_downsample_factor(object_radius_microns: float, base_mag: float, patch_size_pixels: int, mm_per_pixel_at_base: float) -> float`
- **Logic**:
  - Convert object radius from microns to base-pixel units: `radius_base_pixels = object_radius_microns / (mm_per_pixel_at_base * 1000)`
  - Desired extraction magnification: `mag_at_patch = base_mag / downsample_factor`
  - At extraction magnification, mm/pixel = `mm_per_pixel_at_base * downsample_factor`
  - Object radius in extraction pixels: `radius_extract_pixels = object_radius_microns / (mm_per_pixel_at_base * 1000 * downsample_factor)`
  - For the object to "fit" in the patch: `2 * radius_extract_pixels <= patch_size_pixels`
  - Solve for downsample: `downsample_factor >= (2 * object_radius_microns) / (patch_size_pixels * mm_per_pixel_at_base * 1000) / base_mag`
  - Return `max(1.0, computed_downsample)` (downsample cannot be < 1)

### New: `extract_patch_from_geometry` function
- **Signature**: `extract_patch_from_geometry(ts, geometry, patch_size: int, downsample_factor: float, base_mag: float) -> bytes`
- Extracts patch bytes using the same logic as existing `_extract_patch_region`:
  - Compute centroid from geometry (for Polygon: `centroid = geometry.centroid`; for Point: use coordinates directly)
  - Compute `scale = 1.0 / downsample_factor`
  - Compute `magnification = base_mag / downsample_factor`
  - Call `ts.getRegion()` with `units="base_pixels"`
  - Convert RGBA→RGB if needed, save as JPEG quality 85
  - Return JPEG bytes

### New: `estimate_object_radius_from_polygons` function
- **Signature**: `estimate_object_radius_from_polygons(geometries: list[BaseGeometry]) -> float`
- Takes first 5 polygon geometries (coordinates assumed to be in the image's base-magnification pixel space)
- For each polygon, delegates to `get_polygon_radius_in_pixels(geometry)`
- Returns the average radius in base-pixel units
- Caller converts to microns using `mm_per_pixel_at_base`

### New: `get_polygon_radius_in_pixels` function
- **Signature**: `get_polygon_radius_in_pixels(geometry: BaseGeometry) -> float`
- Computes the half-diagonal of the polygon's bounding box using `geometry.bounds` → `(minx, miny, maxx, maxy)`
- Formula: `0.5 * max(maxx - minx, maxy - miny)` — the minimum radius that encloses the bounding box along the longest axis
- Coordinates are treated as base-magnification pixel units
- Returns float radius in base-pixel units

---

## 3. Patch Iterator Abstract Class + Implementations (`patchsorter/api/v1/upload/patch_iterator.py`)

**Note**: Iterators are **not** responsible for patch extraction. They yield metadata only.

### `PatchIterator` abstract base class
- **Signature**: `class PatchIterator(ABC)`
- **Abstract method**: `__iter__(self) -> Iterator[Tuple[BaseGeometry, int | None, uuid.UUID | None]]`
  - Yields: `(geometry, label, uuid)`
  - `geometry`: shapely Polygon or Point
  - `label`: int label class ID or `None`
  - `uuid`: user-provided UUID or `None` (generated later)

### `GeojsonPatchIterator`
- **Constructor**: `__init__(self, geojson_path: str)`
- Uses `osgeo.ogr` to open datasource, iterate layer features
- For each feature:
  - Extract shapely geometry from OGR geometry (via `ExportToWkb` → `shapely.wkb.loads`)
  - Extract label from feature properties if available (e.g., `label`, `class_id`, `label_class_id`)
  - Extract UUID from feature `uid` property if available
- **Raises**: `ValueError` with an informative message if feature geometry is not a Polygon, e.g.: `f"GeojsonPatchIterator only supports Polygon geometries, but feature FID={fid} has geometry type '{geom_type_name}'. Use CsvPatchIterator for point-based coordinates."`

### `CsvPatchIterator`
- **Constructor**: `__init__(self, csv_path: str)`
- Uses `pandas` to read CSV
- Expects columns: `x`, `y` (pixel coordinates), optionally `label`, `uuid`
- For each row:
  - Create shapely `Point(x, y)`
  - Extract label from `label` column if available
  - Extract UUID from `uuid` column if available


### `HybridPatchIterator`
- **Constructor**: `__init__(self, geojson_path: str, csv_path: str)`
- Reads CSV into pandas DataFrame, sets `uuid` column as index for O(1) lookup
- Iterates geojson features via OGR (same geometry/label extraction as `GeojsonPatchIterator`)
- For each feature:
  - Look up `uid` from feature properties in CSV index
  - If matched: use CSV `uuid`, CSV `label`
  - If not matched: generate UUID, use feature label if available

---

## 4. `ProcessRow` Model Update (`patchsorter/api/v1/upload/models.py`)

### Update `ProcessRow`
- Add optional field: `base_mag: float | None = None`

### Add new models
- `ProcessCsvResponse(BaseModel)`:
  - `task_id: str`
  - `status: str`
  - `message: str`

> `ProcessCsvRequest` is **not** a Pydantic model — the CSV is received as a standard FastAPI `UploadFile` parameter directly on the endpoint.

---

## 5. `process_row` Ray Remote Function (`patchsorter/api/v1/upload/actor.py`)

### `@ray.remote` function signature
```python
def process_row(
    process_row_arg: ProcessRow,
    project_id: int,
    session_id: str,
) -> dict:
```

> `max_concurrency` is **not** set — it is only meaningful on Ray actor classes, not on standalone remote functions.

### Execution flow
1. **Get store manager**: `fsman = FileStoreManager()`
2. **Resolve image path**: `image_path = fsman.upload.get_image_path(session_id, process_row_arg.image)`
3. **Open image**: `ts = large_image.open(image_path)`
4. **Determine base_mag**:
   - If `process_row_arg.base_mag` is provided → use it
   - Else → extract from `ts.getMetadata().get("magnification")`
   - Else → raise `ValueError("base_mag not provided and could not be extracted from image metadata")`
5. **Collect image metadata**:
   - `base_mag`, `base_width`, `base_height` from `ts.getMetadata()`
   - `deepzoom_tilesize` from `ts.getMetadata().get("tileWidth", 256)`
6. **Determine iterator** based on which files are present:
   - `mask` present, no `csv` → `GeojsonPatchIterator`
   - `csv` present, no `mask` → `CsvPatchIterator`
   - Both present → `HybridPatchIterator`
7. **Get database session**: `client = get_client()` → `with client.get_session() as session:`
8. **Insert image record**: `result = ImageStore(session).create(...)` → `image_id = result["image_id"]`
9. **Load settings** (passed in from `UploadSessionActor` — see section 6):
   - `patch_size: int` — from project setting `patch_size`
   - `patch_extraction_method: str` — from project setting `patch_extraction_method`
   - `object_radius: float | None` — from project setting `object_radius` (required when method is `"use manual object radius"`)
10. **Determine downsample strategy** from `patch_extraction_method`:
    - `"use estimated object size"` → call `estimate_object_radius_from_polygons` on first 5 geometries from iterator, compute single downsample via `compute_downsample_factor`
    - `"use manual object radius"` → use `object_radius` from settings, compute single downsample via `compute_downsample_factor`
    - `"fit all objects"` → compute per-geometry downsample via `get_polygon_radius_in_pixels` inside the loop
11. **Iterate patches**:
    ```python
    for geometry, label, patch_uuid in iterator:
        computed_downsample = compute_downsample(...)  # single or per-patch
        patch_bytes = extract_patch_from_geometry(ts, geometry, patch_size, computed_downsample, base_mag)
        records.append((patch_uuid, label, image_id, computed_downsample, centroid_x, centroid_y, polygon_wkt, patch_bytes))
    ```
12. **Bulk insert**: `PatchStore(project_id, session).copy_insert(records)`
13. **Move image to permanent storage**: `fsman.nas_write.move_to_permanent(session_id, project_id, image_id, image_filename)`
14. **Return**: `{"image_id": image_id, "patch_count": len(records)}`

### Error handling
- Any exception during processing → no cleanup of DB (session rolls back)
- Exception propagates to caller (entire upload fails)

---

## 6. `UploadSessionActor` updates (`patchsorter/api/v1/upload/actor.py`)

### Actor class declaration
```python
@ray.remote(max_concurrency=2)
class UploadSessionActor:
```

> `max_concurrency=2` allows `process()` to call `ray.get()` on remote tasks without deadlocking the actor's single execution slot.

### Updated `__init__`
- Remove `tempfile.TemporaryDirectory`
- Instantiate `fsman = FileStoreManager()` and store as `self._fsman`
- Call `self._fsman.upload.create_session_dirs(session_id)` to create the session directory structure on disk
- Load project settings from the DB at actor startup:
  ```python
  with get_client().get_session() as session:
      self._settings = SettingStore(session).get_project_settings(project_id)
  ```
  Store as `self._settings: dict` with keys: `patch_size`, `patch_extraction_method`, `object_radius`

### Updated `__ray_shutdown__`
- Replace `self._tmpdir.cleanup()` with `self._fsman.upload.cleanup_session(self._session_id)`

### Updated `save_images` / `save_masks` / `save_patch_csvs`
- Replace `os.path.join(self._tmpdir.name, subdir, filename)` with appropriate `UploadStore` path methods

### Updated `validate_mixed` / `validate_image_csv`
- Pass `self._fsman.upload.get_session_dir(self._session_id)` as the tmpdir argument instead of `self._tmpdir.name`

### Updated `process(self, paths: list[dict]) -> dict`
```python
def process(self, paths: list[dict]) -> dict:
    task_id = str(uuid.uuid4())
    process_rows = [ProcessRow(**p) for p in paths]
    try:
        # Dispatch all tasks, passing pre-loaded settings
        task_refs = [
            process_row.remote(pr, self._project_id, self._session_id, self._settings)
            for pr in process_rows
        ]
        # Block until all complete (any failure raises)
        results = ray.get(task_refs)
        exit_actor()  # only exit on success
        return {
            "task_id": task_id,
            "status": "completed",
            "message": f"Processed {len(results)} image(s)",
            "results": results,
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "status": "failed",
            "message": str(e),
            "results": [],
        }
```

> `exit_actor()` is called **only on success**. On failure the actor remains alive so the session can be inspected or retried by the caller.

---

## 7. Second Endpoint Stub (`patchsorter/api/v1/upload/routes.py`)

### New endpoint
```python
@router.post(
    "/projects/{project_id}/upload/{session_id}/process-csv/",
    response_model=ProcessCsvResponse,
    operation_id="process_upload_csv",
)
def process_upload_csv(
    project_id: int,
    session_id: str,
    csv_file: UploadFile,  # standard FastAPI multipart file upload
) -> ProcessCsvResponse:
    """Stub: later to accept a validated CSV for CSV-only upload flow."""
    return ProcessCsvResponse(
        task_id=str(uuid.uuid4()),
        status="pending",
        message="Not yet implemented",
    )
```

> No separate request model is needed — the CSV arrives as a standard FastAPI `UploadFile` multipart parameter.

---

## Files to Create

| File | Purpose |
|------|---------|
| `patchsorter/api/v1/upload/fsmanager.py` | File system path management via `FileStoreManager`, `NASWriteStore`, `NASReadStore`, `UploadStore` |
| `patchsorter/api/v1/upload/patch_iterator.py` | `PatchIterator` ABC + `GeojsonPatchIterator`, `CsvPatchIterator`, `HybridPatchIterator` |

## Files to Modify

| File | Change |
|------|--------|
| `patchsorter/utils/patch_extraction.py` | Mark existing code as deprecated; add `compute_downsample_factor`, `extract_patch_from_geometry`, `estimate_object_radius_from_polygons`, `get_polygon_radius_in_pixels` |
| `patchsorter/api/v1/upload/models.py` | Add `base_mag` to `ProcessRow`; add `ProcessCsvResponse` |
| `patchsorter/api/v1/upload/actor.py` | Refactor to use `UploadStore` (remove `tempfile`); load settings in `__init__`; add `process_row` remote function; update `process` method |
| `patchsorter/api/v1/upload/routes.py` | Add `process-csv` endpoint stub |
| `patchsorter/config/constants.py` | Add `MOUNTS_PATH = os.path.join('/opt/PatchSorter', 'mounts')` |
| `patchsorter/config/settings_defaults.toml` | Add `patch_extraction_method` (enum, project-scoped) and `object_radius` (string/float, project-scoped) settings |

---

## Key Design Decisions

1. **Iterator responsibility**: Iterators yield `(geometry, label, uuid)` only — no patch extraction. Extraction happens in the calling loop after downsample is determined.

2. **Settings loaded at actor startup**: `UploadSessionActor.__init__` fetches the project's settings from the DB once and stores them on `self._settings`. They are passed through to `process_row` as a plain dict to avoid redundant DB round-trips per image. New settings required in `settings_defaults.toml`:
   - `patch_extraction_method` — enum, project-scoped, allowed values: `["use estimated object size", "use manual object radius", "fit all objects"]`, default `"use estimated object size"`
   - `object_radius` — string (parsed as float at runtime), project-scoped, default `"10.0"` (microns)

3. **Downsample determination**: Driven by `patch_extraction_method` setting:
   - `"use estimated object size"`: Average bounding-box radius of first 5 polygon geometries → single downsample for all patches. Raises error if geojson contains non-Polygon geometries.
   - `"use manual object radius"`: Uses `object_radius` setting (microns) → single downsample for all patches.
   - `"fit all objects"`: Per-polygon bounding-box radius → per-patch downsample.
   ```
   downsample = max(1.0, (2 * radius_microns) / (patch_size * mm_per_pixel_at_base * 1000) / base_mag)
   ```

4. **UUID resolution in Hybrid mode**: CSV `uuid` column used as pandas index for O(1) lookup by geojson feature `uid`. 

5. **Blocking actor**: `ray.get()` on all `process_row` refs ensures any failure propagates and the entire upload session fails atomically.

6. **Session directory management**: `UploadSessionActor.__init__` calls `UploadStore.create_session_dirs()` to create the session directory tree under `mounts/nas_write/tmp/upload_sessions/{session_id}/`. `process_row` assumes the structure exists. On success, `UploadSessionActor.process()` calls `exit_actor()` which triggers `__ray_shutdown__` → `UploadStore.cleanup_session()`. On failure, the session dir is left intact for debugging.
