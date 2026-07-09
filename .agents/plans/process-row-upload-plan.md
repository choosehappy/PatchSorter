# Implementation Plan: `process_row` Ray Task for Upload Processing

## 1. File System Manager (`patchsorter/api/v1/upload/fsmanager.py`)

### `FileStore` abstract base class
- **Base class** for managing paths with a configurable sub_path
- Constructor: `__init__(self, sub_path: str)`
- Sets `self.base_path` from constants (e.g., `/opt/PatchSorter/mounts/nas_write`)
- Sets `self.full_path = os.path.join(self.base_path, sub_path)`
- Provides methods:
  - `get_base_path()` — returns the base mounts path
  - `get_full_path(filepath=None)` — returns `self.full_path` or joins filepath
  - `global_to_relative(path)` — converts absolute path to relative (w.r.t. `self.full_path`)
  - `relative_to_global(path)` — converts relative path to absolute (w.r.t. `self.full_path`)

### `NASWriteStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `"nas_write"`
- **Purpose**: PatchSorter writable storage (uploaded files, projects, masks)
- **Methods**:
  - `get_project_path(project_id: int, relative: bool = False)` — returns `projects/proj_{project_id}`
  - `get_project_image_path(project_id: int, image_id: int, relative: bool = False)` — returns `projects/proj_{project_id}/images/img_{image_id}`
  - `get_project_mask_path(project_id: int, image_id: int, relative: bool = False)` — returns `{project_image_path}/masks`
  - `get_temp_path(relative: bool = False)` — returns `temp`

### `NASReadStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `"nas_read"`
- **Purpose**: Read-only folder/CSV uploads mounted to the PatchSorter Docker container (outside of session-managed paths)
- **Methods**:
  - `get_input_images_path(relative: bool = False)` — returns `images`
  - `get_input_masks_dir(relative: bool = False)` — returns `masks`

### `UploadStore` class (inherits `FileStore`)
- **Constructor**: `__init__(self)`
- **Sub-path**: `os.path.join("nas_write", "tmp", "upload_sessions")` (root within nas_write mounts)
- **Purpose**: Per-upload-session temporary storage
- **Methods**:
  - `get_session_dir(session_id: str, relative: bool = False)` — returns `{session_id}/`
  - `get_images_dir(session_id: str, relative: bool = False)` — returns `{session_id}/images/`
  - `get_masks_dir(session_id: str, relative: bool = False)` — returns `{session_id}/masks/`
  - `get_patch_csvs_dir(session_id: str, relative: bool = False)` — returns `{session_id}/patch_csvs/`
  - `get_image_path(session_id: str, filename: str, relative: bool = False)` — returns full path to uploaded image
  - `get_mask_path(session_id: str, filename: str, relative: bool = False)` — returns full path to uploaded mask
  - `get_patch_csv_path(session_id: str, filename: str, relative: bool = False)` — returns full path to uploaded CSV

### `FileSystemManager` class
- **Constructor**: `__init__(self)`
- **Manages three FileStore instances**:
  - `self.nas_write = NASWriteStore()` — for PatchSorter writable storage
  - `self.nas_read = NASReadStore()` — for read-only mounted folder/CSV uploads
  - `self.upload_store = UploadStore()` — for upload session temp storage
- **Methods**:
  - `get_session_path(session_id: str) -> UploadStore` — returns the upload store (scoped to session via methods)
  - `get_project_image_path(project_id: int, image_id: int) -> str` — delegates to `nas_write.get_project_image_path()`
  - `move_to_permanent(session_id, project_id, image_id, filename)` — atomic `shutil.move` from upload store to nas_write permanent dir
  - `cleanup_session(session_id)` — removes upload session directory via `shutil.rmtree`

### Path structure

```
nas_write/
├── tmp/
│   └── upload_sessions/
│       └── {session_id}/
│           ├── images/
│           ├── masks/
│           └── patch_csvs/
├── temp/
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
- Takes first 5 polygon geometries
- For each polygon, compute `geometry.buffer(0).distance(geometry.centroid)` (mean radius of vertices from centroid)
- Return the average radius in base-pixel units
- Caller converts to microns using `mm_per_pixel_at_base`

### New: `get_polygon_radius_in_pixels` function
- **Signature**: `get_polygon_radius_in_pixels(geometry: BaseGeometry) -> float`
- Computes mean distance of polygon vertices from centroid in base-pixel units
- Returns float radius

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
- **Raises**: `ValueError` if feature is not a Polygon (points not allowed in geojson-only mode)

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
- `ProcessCsvRequest(BaseModel)`:
  - `csv_content: str` — base64-encoded or raw CSV content
- `ProcessCsvResponse(BaseModel)`:
  - `task_id: str`
  - `status: str`
  - `message: str`

---

## 5. `process_row` Ray Remote Function (`patchsorter/api/v1/upload/actor.py`)

### `@ray.remote(max_concurrency=1)` function signature
```python
def process_row(
    process_row_arg: ProcessRow,
    project_id: int,
    session_id: str,
) -> dict:
```

### Execution flow
1. **Get fsmanager**: `fsman = FileSystemManager()`
2. **Get session path**: `session_path = fsman.upload_store` (UploadStore already scoped to session by UploadSessionActor)
3. **Resolve image path**: `image_path = session_path.get_image_path(session_id, process_row_arg.image)`
4. **Open image**: `ts = large_image.open(image_path)`
5. **Determine base_mag**:
   - If `process_row_arg.base_mag` is provided → use it
   - Else → extract from `ts.getMetadata()`
   - Else → raise `ValueError("base_mag not provided and could not be extracted from image")`
6. **Collect image metadata**:
   - `base_mag`, `base_width`, `base_height` from `ts.getMetadata()`
   - `deepzoom_tilesize` from `ts.getMetadata()["tilewidth"]` / `["tileheight"]`
7. **Determine iterator** based on which files are present:
   - `mask` present → `GeojsonPatchIterator`
   - `csv` present only → `CsvPatchIterator`
   - Both present → `HybridPatchIterator`
8. **Get database session**: `client = get_client()` → `with client.get_session() as session:`
9. **Insert image record**: `ImageStore(session).create(...)` → get `image_id`
10. **Determine patch extraction method**:
    - Read project setting `patch_extraction_method` (enum: `"use estimated object size"`, `"use manual object radius"`, `"fit all objects"`)
    - If `"use manual object radius"` → read project setting `object_radius` (microns)
    - Compute downsample for each patch using `compute_downsample_factor` or per-polygon radius
    - **Comment**: "In the future, this selection may be driven by a project-level setting rather than a hardcoded lookup"
11. **Iterate patches**:
    ```python
    for geometry, label, uuid in iterator:
        computed_downsample = compute_downsample(...)
        patch_bytes = extract_patch_from_geometry(ts, geometry, patch_size, computed_downsample, base_mag)
        records.append((uuid, label, image_id, computed_downsample, centroid_x, centroid_y, polygon_wkt, patch_bytes))
    ```
12. **Bulk insert**: `PatchStore(project_id, session).copy_insert(records)`
13. **Move image to permanent storage**: `fsman.move_to_permanent(session_id, project_id, image_id, image_filename)`
14. **Return**: `{"image_id": image_id, "patch_count": len(records)}`

### Error handling
- Any exception during processing → no cleanup of DB (session rolls back)
- Exception propagates to caller (entire upload fails)

---

## 6. `process` Method in `UploadSessionActor` (`patchsorter/api/v1/upload/actor.py`)

### Updated `process(self, paths: list[dict]) -> dict`
```python
def process(self, paths: list[dict]) -> dict:
    task_id = str(uuid.uuid4())
    process_rows = [ProcessRow(**p) for p in paths]
    try:
        # Dispatch all tasks
        task_refs = [
            process_row.remote(pr, self._project_id, self._session_id)
            for pr in process_rows
        ]
        # Block until all complete (any failure raises)
        results = ray.get(task_refs)
        return {
            "task_id": task_id,
            "status": "completed",
            "message": f"Processed {len(results)} image(s)",
            "results": [r for r in results],
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "status": "failed",
            "message": str(e),
            "results": [],
        }
    finally:
        exit_actor()
```

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
    csv_file: UploadFile,
) -> ProcessCsvResponse:
    """Stub: later to accept a validated CSV for CSV-only upload flow."""
    return ProcessCsvResponse(
        task_id=str(uuid.uuid4()),
        status="pending",
        message="Not yet implemented",
    )
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `patchsorter/api/v1/upload/fsmanager.py` | File system path management, session/permanent storage, file moves |
| `patchsorter/api/v1/upload/patch_iterator.py` | `PatchIterator` ABC + `GeojsonPatchIterator`, `CsvPatchIterator`, `HybridPatchIterator` |

## Files to Modify

| File | Change |
|------|--------|
| `patchsorter/utils/patch_extraction.py` | Mark existing code as deprecated; add `compute_downsample_factor`, `extract_patch_from_geometry`, `estimate_object_radius_from_polygons`, `get_polygon_radius_in_pixels` |
| `patchsorter/api/v1/upload/models.py` | Add `base_mag` to `ProcessRow`; add `ProcessCsvRequest`, `ProcessCsvResponse` |
| `patchsorter/api/v1/upload/actor.py` | Add `process_row` ray remote function; implement `process` method (blocking) |
| `patchsorter/api/v1/upload/routes.py` | Add `process-csv` endpoint stub |

---

## Key Design Decisions

1. **Iterator responsibility**: Iterators yield `(geometry, label, uuid)` only — no patch extraction. Extraction happens in the calling loop after downsample is determined.

2. **Downsample determination**: Driven by project setting `patch_extraction_method`:
   - `"use estimated object size"`: Average polygon radius of first 5 features → single downsample for all patches. Raises error if geojson contains Points.
   - `"use manual object radius"`: Uses project setting `object_radius` (microns) → single downsample for all patches.
   - `"fit all objects"`: Per-polygon radius → per-patch downsample.

3. **Object radius to downsample formula**:
   ```
   downsample = max(1.0, (2 * radius_microns) / (patch_size * mm_per_pixel_at_base * 1000) / base_mag)
   ```

4. **UUID resolution in Hybrid mode**: CSV `uuid` column used as pandas index for O(1) lookup by geojson feature `uid`.

5. **Blocking actor**: `ray.get()` on all `process_row` refs ensures any failure propagates and the entire upload session fails atomically.

6. **Temp directory management**: UploadSessionActor creates and owns the temp directory lifecycle. process_row assumes the directory structure already exists and does not create or clean up temp directories.
