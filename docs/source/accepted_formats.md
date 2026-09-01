# Accepted Formats

This page documents the accepted file formats for images, masks, patch CSV files, and image CSV files in PatchSorter.

## Images

PatchSorter extracts patches from digital pathology images, with each patch representing an object of interest (e.g., a tubule, cell nucleus, or glomerulus)

PatchSorter accepts the following image formats:

| Extension | Description |
|-----------|-------------|
| `.tif`, `.tiff` | TIFF/BigTIFF images |
| `.png` | PNG images |
| `.jpg`, `.jpeg` | JPEG images |
| `.svs` | Aperio SVS whole-slide images |
| `.ndpi` | Hamamatsu NDPI whole-slide images |
| `.vms`, `.vmu` | Leica SCN whole-slide images |
| `.scn` | Leica SCN whole-slide images |
| `.mrxs` | Philips MRXS whole-slide images |

PatchSorter uses [OpenSlide](https://openslide.org/) to read whole-slide image formats. All OpenSlide-compatible formats are supported.

## Masks

PatchSorter can use polygons stored in mask files to locate and extract objects of interest.

Mask files must be in **GeoJSON** format (`.geojson` extension).

### Requirements

- Only **Polygon** geometries are supported (Point and LineString geometries will be rejected).
- The mask file must match the **base name** of the corresponding image file (e.g., `sample.svs` → `sample.geojson`).


### Supported feature properties

GeoJSON feature `properties` may include the following fields:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `label` | int | No | Label class ID for the polygon |
| `class_id` | int | No | Alias for `label` |
| `label_class_id` | int | No | Alias for `label` |
| `uid` | string (UUID) | No | User-provided UUID for the mask feature; if omitted, a UUID is generated automatically |

If none of `label`, `class_id`, or `label_class_id` are present, the feature is assigned the **unassigned** label class ID.

### Sample:

```geojson
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "label": 1,
        "uid": "550e8400-e29b-41d4-a716-446655440000"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [54993, 7573],
            [54865, 7577],
            [54993, 7573]
          ]
        ]
      }
    }
  ]
}

```

## Patch CSV Files

Patch CSV files define point-based patch locations with optional label and UUID metadata. A Patch CSV file can be supplied in addition to or instead of a Mask geojson file.

### Required columns

| Column | Type | Description |
|--------|------|-------------|
| `centroid_x` | float | X pixel coordinate of the patch centroid within the image |
| `centroid_y` | float | Y pixel coordinate of the patch centroid within the image |
| `width` | int | Patch width in pixels |
| `height` | int | Patch height in pixels |

### Optional columns

| Column | Type | Description |
|--------|------|-------------|
| `label` | int | Label class ID for the patch |
| `patch_uid` | string (UUID) | User-provided UUID for the patch |
| `uuid` | string (UUID) | Alias for `patch_uid` |

### Naming convention

When uploading patch CSV files individually (not via the CSV file list), each patch CSV file must match the **base name** of the corresponding image file (e.g., `sample.svs` → `sample.csv`).

## Image CSV File

The image CSV file (used in the **CSV File List** upload approach) is a manifest that maps each image to its associated mask and patch CSV files.

We recommend uploading an Image CSV file if you want to avoid file naming conventions for your image/mask/patch csv files, or if you are using patchsorter within an automated pipeline.

### Header row

The CSV must have a header row with exactly these three columns:

| Column | Required | Description |
|--------|----------|-------------|
| `image` | Yes | Server path to the scan image file |
| `mask` | Only if `patch_csv` is not supplied | Server path to the mask GeoJSON file (leave empty if not applicable) |
| `patch_csv` | Only if `mask` is not supplied | Server path to the patch CSV file (leave empty if not applicable) |

### Path format

Each row contains **server paths** relative to the `nas_read` mount on the server.

#### Example

Folder structure within `/opt/PatchSorter/mounts/nas_read`
```
data/
├── images/
│   ├── sample1.svs
│   ├── sample2.svs
│   └── sample3.svs
├── masks/
│   ├── sample1.geojson
│   └── sample3.geojson
└── patch_csvs/
    ├── sample1.csv
    └── sample2.csv
```

Resulting Patch CSV
```csv
image,mask,patch_csv
data/images/sample1.svs,data/masks/sample1.geojson,data/patch_csvs/sample1.csv
data/images/sample2.svs,,data/patch_csvs/sample2.csv
data/images/sample3.svs,data/masks/sample3.geojson,
```