import type { ReviewRow } from '../../api_client'

export function countMissingBaseMag(
    reviewData: ReviewRow[] | null,
    selectedIndices: Set<number>,
): number {
    if (!reviewData) return 0
    let count = 0
    for (const idx of selectedIndices) {
        if (reviewData[idx]?.base_mag == null) count++
    }
    return count
}
