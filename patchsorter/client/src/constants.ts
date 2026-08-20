
// Shared constants for PatchSorter client

export const WORLD_SIZE = 4096


// Upload
export const ACCEPTED_EXTS = /\.(tif|tiff|png|jpg|jpeg)$/i
export const ACCEPT_ATTR = '.tif,.tiff,.png,.jpg,.jpeg'

// Magnification options for review step editor
export const MAGNIFICATION_OPTIONS: number[] = [5, 10, 20, 40]
export const QUAD_HALF = 32
export const QUAD_PADDING = 2

export const REFRESH_INTERVAL_OPTIONS: { label: string; ms: number | null }[] = [
    { label: '1s', ms: 1000 },
    { label: '5s', ms: 5000 },
    { label: '10s', ms: 10000 },
    { label: '30s', ms: 30000 },
    { label: 'Off', ms: null },
]

export const DEFAULT_REFRESH_INTERVAL_MS = REFRESH_INTERVAL_OPTIONS[2].ms

export const PAGE_SIZE_OPTIONS = [25, 50, 100, 200]

export const MIN_PATCH_SIZE = 40
export const MAX_PATCH_SIZE = 300
export const DEFAULT_PATCH_SIZE = 80

// QueryRange (inverted: density=0 → large query box, density=100 → small query box)
export const DEFAULT_QUERY_RANGE = 16
export const MIN_QUERY_RANGE = 2
export const MAX_QUERY_RANGE = 64

// Limit constrained to perfect squares
export const PERFECT_SQUARE_LIMITS = [1, 4, 9, 16, 25, 36, 49]

// Fixed spacing between sample points in pixels
export const FIXED_SPACING_PIXELS = 10

// Fixed limit for mouse-down hover grid (3x3)
export const FIXED_MOUSEDOWN_LIMIT = 9
