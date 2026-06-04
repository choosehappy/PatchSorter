import { useState } from 'react'
import PatchImage from './PatchImage'
import './patchGallery.css'
import type { PatchResponse, LabelClassResponse } from '../api_client'

const PAGE_SIZE_OPTIONS = [12, 24, 48, 96]
const MIN_PATCH_SIZE = 40
const MAX_PATCH_SIZE = 120
const DEFAULT_PATCH_SIZE = 80

export default function PatchGallery({
    projectId,
    patches,
    isLoading,
    isFetchingNextPage,
    canGoNext,
    canGoPrev,
    onNext,
    onPrev,
    pageSize,
    setPageSize,
    totalPatches,
    currentPage,
    hasLasso,
    labelClasses,
}: {
    projectId: number
    patches: PatchResponse[]
    isLoading: boolean
    isFetchingNextPage: boolean
    canGoNext: boolean
    canGoPrev: boolean
    onNext: () => void
    onPrev: () => void
    pageSize: number
    setPageSize: (s: number) => void
    totalPatches: number | null
    currentPage: number
    hasLasso: boolean
    labelClasses: LabelClassResponse[]
}) {
    const [selectAll, setSelectAll] = useState(false)
    const [patchSize, setPatchSize] = useState(DEFAULT_PATCH_SIZE)

    const totalPages = totalPatches !== null ? Math.max(1, Math.ceil(totalPatches / pageSize)) : null
    const loading = isLoading || isFetchingNextPage

    const gridStyle = {
        gridTemplateColumns: `repeat(auto-fill, minmax(${patchSize}px, 1fr))`,
        gap: '8px',
    }

    return (
        <div className="patch-gallery">
            <div className="gallery-toolbar">

                <label className="toolbar-group checkbox-group">
                    <input
                        type="checkbox"
                        checked={selectAll}
                        onChange={e => setSelectAll(e.target.checked)}
                    />
                    Select All
                </label>

                <div className="toolbar-group">
                    <label>
                        Size: {patchSize}px
                        <input
                            type="range"
                            min={MIN_PATCH_SIZE}
                            max={MAX_PATCH_SIZE}
                            value={patchSize}
                            onChange={e => setPatchSize(Number(e.target.value))}
                        />
                    </label>
                </div>

                <div className="toolbar-group">
                    <label>
                        Count:
                        <select value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
                            {PAGE_SIZE_OPTIONS.map(opt => (
                                <option key={opt} value={opt}>{opt}</option>
                            ))}
                        </select>
                    </label>
                </div>

                <div className="toolbar-group">
                    <span>
                        Page {currentPage + 1}{totalPages !== null ? ` of ${totalPages}` : ''}
                        {totalPatches !== null ? ` · ${totalPatches} patches` : ''}
                    </span>
                    <button onClick={onPrev} disabled={!canGoPrev || loading}>
                        Prev
                    </button>
                    <button onClick={onNext} disabled={!canGoNext || loading}>
                        Next
                    </button>
                </div>
            </div>

            <div className="gallery-scroll">
                {!hasLasso ? (
                    <div className="gallery-loading">Draw a lasso on the map to browse patches.</div>
                ) : isLoading && patches.length === 0 ? (
                    <div className="gallery-loading">Loading patches...</div>
                ) : (
                    <div className="gallery-grid" style={gridStyle}>
                        {patches.map(patch => (
                            <PatchImage
                                key={patch.patch_id}
                                projectId={projectId}
                                patch={patch}
                                labelClasses={labelClasses}
                                isSelected={selectAll}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
