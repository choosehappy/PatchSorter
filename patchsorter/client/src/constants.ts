
// Shared constants for PatchSorter client

export const WORLD_SIZE = 4096



// Quad base half-size in grid cells (scales by 2^(-zoom) for fixed visual size)
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

// Sampling density slider (single slider replaces queryRange + numSamples)
export const DEFAULT_SAMPLING_DENSITY = 50
export const MIN_SAMPLING_DENSITY = 0
export const MAX_SAMPLING_DENSITY = 100

// NumSamples range (few regions, deep sampling at density=0 → many regions, shallow sampling at density=100)
export const DEFAULT_NUM_SAMPLES = 20
export const MIN_NUM_SAMPLES = 5
export const MAX_NUM_SAMPLES = 200

// QueryRange (inverted: density=0 → large query box, density=100 → small query box)
export const DEFAULT_QUERY_RANGE = 16
export const MIN_QUERY_RANGE = 2
export const MAX_QUERY_RANGE = 64

// Limit range (inverted: density=0 → high limit, density=100 → low limit)
export const MIN_LIMIT = 1
export const MAX_LIMIT = 50