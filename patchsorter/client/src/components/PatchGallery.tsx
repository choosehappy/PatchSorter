import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
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
    onLabelAssign,
    lastAssignedClassId,
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
    onLabelAssign?: (labelClassId: number) => void
    lastAssignedClassId: number | null
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

    // Set when a box-select finishes, so the click that follows it is ignored
    const justDraggedRef = useRef(false)

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

    const sortedClasses = useMemo(
        () => [...labelClasses].sort((a, b) => a.label_class_id - b.label_class_id),
        [labelClasses]
    )

    const lastClass = useMemo(
        () => sortedClasses.find(c => c.label_class_id === lastAssignedClassId),
        [sortedClasses, lastAssignedClassId]
    )

    function handleClassClick(classId: number) {
        if (onLabelAssign) {
            onLabelAssign(classId)
        }
    }

    // Keyboard shortcuts for number keys 1-9 and Enter
    useEffect(() => {
        function handleKeyDown(e: KeyboardEvent) {
            // Only handle if we have label classes and a callback
            if (!onLabelAssign || sortedClasses.length === 0) return

            // Check if we're in a text-focused input where typing matters
            const target = e.target as HTMLElement
            if (target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return
            if (target.tagName === 'INPUT' && ['text', 'number', 'search', 'email', 'password', 'url'].includes((target as HTMLInputElement).type)) return

            if (e.key >= '1' && e.key <= '9') {
                const idx = parseInt(e.key, 10) - 1
                if (idx < sortedClasses.length) {
                    e.preventDefault()
                    onLabelAssign(sortedClasses[idx].label_class_id)
                    return
                }
            }

            if (e.key === 'Enter' && lastAssignedClassId !== null) {
                e.preventDefault()
                onLabelAssign(lastAssignedClassId)
            }
        }

        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [onLabelAssign, sortedClasses, lastAssignedClassId])

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
            justDraggedRef.current = true

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
        if (e.button !== 0 || !gridRef.current) return
        // Ignore presses on the scroll container's own scrollbars
        const el = e.currentTarget
        const r = el.getBoundingClientRect()
        if (e.clientX - r.left >= el.clientWidth || e.clientY - r.top >= el.clientHeight) return

        e.preventDefault()
        justDraggedRef.current = false
        const gridRect = gridRef.current.getBoundingClientRect()
        dragState.current = {
            active: true,
            startX: e.clientX - gridRect.left,
            startY: e.clientY - gridRect.top,
        }
    }

    function handleScrollClick(e: React.MouseEvent<HTMLDivElement>) {
        if (justDraggedRef.current) {
            justDraggedRef.current = false
            return
        }
        if (!(e.target as HTMLElement).closest('[data-patch-id]')) {
            onSelectionChange([])
        }
    }

    return (
        <div className="patch-gallery">
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
                                    onClick={() => {
                                        // The scroll container's click handler resets this flag
                                        if (justDraggedRef.current) return
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

            {/* Label footer */}
            <div className="gallery-label-footer">
                <div className="gallery-label-classes">
                    {sortedClasses.map((lc, idx) => {
                        const isLastAssigned = lc.label_class_id === lastAssignedClassId
                        const showNumber = idx < 9
                        return (
                            <button
                                key={lc.label_class_id}
                                className={`gallery-label-item${isLastAssigned ? ' active' : ''}`}
                                onClick={() => handleClassClick(lc.label_class_id)}
                            >
                                {showNumber && (
                                    <span className="gallery-label-number">[{idx + 1}]</span>
                                )}
                                <span
                                    className="gallery-label-swatch"
                                    style={{ backgroundColor: lc.color_code ?? '#cccccc' }}
                                />
                                <span className="gallery-label-name">{lc.name}</span>
                            </button>
                        )
                    })}
                </div>
                {lastClass && onLabelAssign && (
                    <button
                        className="gallery-last-assigned"
                        onClick={() => handleClassClick(lastClass.label_class_id)}
                    >
                        <span
                            className="gallery-label-swatch"
                            style={{ backgroundColor: lastClass.color_code ?? '#cccccc' }}
                        />
                        <span className="gallery-label-name">{lastClass.name}</span>
                        <span className="gallery-last-assigned-text">(press Enter to assign)</span>
                    </button>
                )}
            </div>
        </div>
    )
}
