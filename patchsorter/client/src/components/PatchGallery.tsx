import { useState, useEffect, useCallback } from 'react'
import { client } from '../api_client/client.gen'
import PatchImage from './PatchImage'
import './patchGallery.css'

interface PatchRow {
    patch_id: number
    patch_uid: string
    label_class_id: number
    pred_label_class_id: number | null
    patch_image: string
}

const PAGE_SIZE_OPTIONS = [12, 24, 48, 96]
const MIN_PATCH_SIZE = 40
const MAX_PATCH_SIZE = 120
const DEFAULT_PATCH_SIZE = 80
const DEFAULT_PAGE_SIZE = 24

export default function PatchGallery({ projectId }: { projectId: number }) {
    const [patches, setPatches] = useState<PatchRow[]>([])
    const [cursor, setCursor] = useState(0)
    const [loading, setLoading] = useState(false)
    const [selectAll, setSelectAll] = useState(false)
    const [patchSize, setPatchSize] = useState(DEFAULT_PATCH_SIZE)
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
    const [hasNext, setHasNext] = useState(true)

    const fetchPatches = useCallback(async (pageCursor: number) => {
        setLoading(true)
        try {
            const res = await client.get({
                path: { project_id: projectId },
                query: { cursor: pageCursor, limit: pageSize },
                url: '/projects/{project_id}/patches/',
            })
            if (res.data && Array.isArray(res.data)) {
                setPatches(res.data as PatchRow[])
                setHasNext(res.data.length >= pageSize)
            } else {
                setPatches([])
                setHasNext(false)
            }
        } catch (err) {
            console.error('Failed to fetch patches:', err)
            setPatches([])
            setHasNext(false)
        } finally {
            setLoading(false)
        }
    }, [projectId, pageSize])

    useEffect(() => {
        fetchPatches(0)
    }, [fetchPatches])

    function handlePrev() {
        if (cursor <= 0) return
        const newCursor = patches.length > 0 ? patches[patches.length - 1].patch_id : cursor
        const nextCursor = Math.max(0, newCursor - 1)
        setCursor(nextCursor)
        fetchPatches(nextCursor)
    }

    function handleNext() {
        if (!hasNext || patches.length === 0) return
        const newCursor = patches[patches.length - 1].patch_id
        setCursor(newCursor)
        fetchPatches(newCursor)
    }

    const cols = Math.max(2, Math.floor(320 / patchSize))
    const gridStyle = {
        gridTemplateColumns: `repeat(auto-fill, minmax(${patchSize}px, 1fr))`,
        gap: '8px',
    }

    return (
        <div className="patch-gallery">
            <div className="gallery-toolbar">
                <div className="toolbar-group">
                    <button onClick={handlePrev} disabled={cursor <= 0 || loading}>
                        Prev
                    </button>
                    <button onClick={handleNext} disabled={!hasNext || loading}>
                        Next
                    </button>
                </div>

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
            </div>

            <div className="gallery-scroll">
                {loading && patches.length === 0 ? (
                    <div className="gallery-loading">Loading patches...</div>
                ) : (
                    <div className="gallery-grid" style={gridStyle}>
                        {patches.map(patch => (
                            <PatchImage
                                key={patch.patch_id}
                                patchImageBase64={patch.patch_image}
                                gtLabelClassId={patch.label_class_id}
                                predLabelClassId={patch.pred_label_class_id}
                                isSelected={selectAll}
                            />
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
