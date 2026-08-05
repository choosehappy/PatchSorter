import { useState, useRef, useEffect, useMemo } from 'react'
import PatchImage from './PatchImage'
import './patchGallery.css'
import type { PatchResponse, LabelClassResponse } from '../api_client'
import { PAGE_SIZE_OPTIONS, MIN_PATCH_SIZE, MAX_PATCH_SIZE, DEFAULT_PATCH_SIZE } from '../constants'

interface SelectionRect {
    left: number
    top: number
    width: number
    height: number
}

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
    selectedPatches,
    onSelectionChange,
    onHoverChange,
    onSelectAllChange,
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
    selectedPatches: PatchResponse[]
    onSelectionChange: (patches: PatchResponse[]) => void
    onHoverChange: (patch: PatchResponse | null) => void
    onSelectAllChange?: (selectAll: boolean) => void
}) {
    const [selectAll, setSelectAll] = useState(false)
    const [patchSize, setPatchSize] = useState(DEFAULT_PATCH_SIZE)
    const [selectionRect, setSelectionRect] = useState<SelectionRect | null>(null)

    const gridRef = useRef<HTMLDivElement>(null)
    const dragState = useRef<{
        active: boolean
        startX: number
        startY: number
    }>({ active: false, startX: 0, startY: 0 })

    const selectedIds = useMemo(
        () => new Set(selectedPatches.map(p => p.patch_id)),
        [selectedPatches]
    )

    const totalPages = totalPatches !== null ? Math.max(1, Math.ceil(totalPatches / pageSize)) : null
    const loading = isLoading || isFetchingNextPage

    const gridStyle = {
        gridTemplateColumns: `repeat(auto-fill, minmax(${patchSize}px, 1fr))`,
        gap: '8px',
    }

    // Attach window-level drag listeners
    useEffect(() => {
        function onMouseMove(e: MouseEvent) {
            if (!dragState.current.active || !gridRef.current) return
            const gridRect = gridRef.current.getBoundingClientRect()
            const endX = e.clientX - gridRect.left
            const endY = e.clientY - gridRect.top
            const { startX, startY } = dragState.current
            setSelectionRect({
                left: Math.min(startX, endX),
                top: Math.min(startY, endY),
                width: Math.abs(endX - startX),
                height: Math.abs(endY - startY),
            })
        }

        function onMouseUp(e: MouseEvent) {
            if (!dragState.current.active || !gridRef.current) return
            dragState.current.active = false
            setSelectionRect(null)

            const gridRect = gridRef.current.getBoundingClientRect()
            const { startX, startY } = dragState.current
            const endX = e.clientX - gridRect.left
            const endY = e.clientY - gridRect.top

            // Only act if the drag covered a meaningful area
            if (Math.abs(endX - startX) <= 4 && Math.abs(endY - startY) <= 4) return

            const selLeft = Math.min(startX, endX) + gridRect.left
            const selTop = Math.min(startY, endY) + gridRect.top
            const selRight = Math.max(startX, endX) + gridRect.left
            const selBottom = Math.max(startY, endY) + gridRect.top

            const patchDivs = gridRef.current.querySelectorAll<HTMLElement>('[data-patch-id]')
            const newlySelected: PatchResponse[] = []
            patchDivs.forEach(div => {
                const r = div.getBoundingClientRect()
                const overlaps =
                    r.left < selRight &&
                    r.right > selLeft &&
                    r.top < selBottom &&
                    r.bottom > selTop
                if (overlaps) {
                    const id = Number(div.dataset.patchId)
                    const patch = patches.find(p => p.patch_id === id)
                    if (patch && !selectedIds.has(id)) newlySelected.push(patch)
                }
            })
            if (newlySelected.length > 0) {
                onSelectionChange([...selectedPatches, ...newlySelected])
            }
        }

        window.addEventListener('mousemove', onMouseMove)
        window.addEventListener('mouseup', onMouseUp)
        return () => {
            window.removeEventListener('mousemove', onMouseMove)
            window.removeEventListener('mouseup', onMouseUp)
        }
    }, [patches, selectedPatches, selectedIds, onSelectionChange])

    function handleScrollMouseDown(e: React.MouseEvent<HTMLDivElement>) {
        if (!(e.ctrlKey || e.metaKey) || !gridRef.current) return
        e.preventDefault()
        const gridRect = gridRef.current.getBoundingClientRect()
        dragState.current = {
            active: true,
            startX: e.clientX - gridRect.left,
            startY: e.clientY - gridRect.top,
        }
    }

    function handleScrollClick(e: React.MouseEvent<HTMLDivElement>) {
        if (e.ctrlKey || e.metaKey) return
        if (!(e.target as HTMLElement).closest('[data-patch-id]')) {
            onSelectionChange([])
        }
    }

    function handleContextMenu(e: React.MouseEvent) {
        if (e.ctrlKey || e.metaKey) e.preventDefault()
    }

    return (
        <div className="patch-gallery" onContextMenu={handleContextMenu}>
            <div className="gallery-toolbar">

                <label className="toolbar-group checkbox-group">
                    <input
                        type="checkbox"
                        checked={selectAll}
                        onChange={e => {
                            setSelectAll(e.target.checked)
                            onSelectAllChange?.(e.target.checked)
                        }}
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

            <div className="gallery-scroll" onMouseDown={handleScrollMouseDown} onClick={handleScrollClick}>
                {!hasLasso ? (
                    <div className="gallery-loading">Draw a lasso on the map to browse patches.</div>
                ) : isLoading && patches.length === 0 ? (
                    <div className="gallery-loading">Loading patches...</div>
                ) : (
                    <div className="gallery-grid-wrapper">
                        <div
                            className="gallery-grid"
                            style={gridStyle}
                            ref={gridRef}
                        >
                            {patches.map(patch => (
                                <div
                                    key={patch.patch_id}
                                    data-patch-id={patch.patch_id}
                                    className="patch-grid-cell"
                                    onMouseEnter={() => onHoverChange(patch)}
                                    onMouseLeave={() => onHoverChange(null)}
                                    onMouseDown={e => {
                                        if (e.button !== 0 || !(e.ctrlKey || e.metaKey)) return
                                        e.preventDefault()
                                        if (selectedIds.has(patch.patch_id)) {
                                            onSelectionChange(selectedPatches.filter(p => p.patch_id !== patch.patch_id))
                                        } else {
                                            onSelectionChange([...selectedPatches, patch])
                                        }
                                    }}
                                >
                                    <PatchImage
                                        projectId={projectId}
                                        patch={patch}
                                        labelClasses={labelClasses}
                                        isSelected={selectAll || selectedIds.has(patch.patch_id)}
                                    />
                                </div>
                            ))}
                        </div>
                        {selectionRect && (
                            <div
                                className="gallery-selection-rect"
                                style={{
                                    left: selectionRect.left,
                                    top: selectionRect.top,
                                    width: selectionRect.width,
                                    height: selectionRect.height,
                                }}
                            />
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
