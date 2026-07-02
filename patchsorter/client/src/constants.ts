
// Shared constants for PatchSorter client

export const WORLD_SIZE = 4096

// Patch sampling
export const PATCH_NUM_SAMPLES = 200
export const PATCH_QUERY_RANGE = 16
export const PATCH_QUERY_RANGE_POINT = 16

// Quad base half-size in grid cells (scales by 2^(-zoom) for fixed visual size)
export const QUAD_HALF = 64
export const HOVER_TIMEOUT_MS = 100

// Upload
export const ACCEPTED_EXTS = /\.(tif|tiff|png|jpg|jpeg)$/i
export const ACCEPT_ATTR = '.tif,.tiff,.png,.jpg,.jpeg'