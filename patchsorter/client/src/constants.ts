
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