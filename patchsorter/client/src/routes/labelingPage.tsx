import { useState, useEffect, useMemo, Children, cloneElement } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { client } from '../api_client/client.gen'
import './labelingPage.css'
import Viewport, { type MapBounds } from '../components/viewport'
import ConfusionMatrix, { type ConfusionData } from '../components/confusionMatrix'
import RefreshTimer from '../components/refreshTimer'
import PatchGallery from '../components/PatchGallery'
import { getConfusionMatrixProjectsProjectIdConfusionMatrixGet, infoProjectsProjectIdInfoGet, type PatchResponse, type WorldInfo } from '../api_client'

// ---- ToggleButtonGroup (lightweight, no react-bootstrap dependency) ----

interface ToggleButtonGroupProps {
    children: React.ReactNode
    name: string
    activeKey: string
    onChange: (value: string) => void
}

interface ToggleButtonProps {
    value: string
    active: boolean
    onChange: (value: string) => void
    children: React.ReactNode
    title?: string
}

function ToggleButtonGroup({ children, name, activeKey, onChange }: ToggleButtonGroupProps) {
    return (
        <div className="toggle-button-group">
            {Children.map(children, child =>
                cloneElement(child as React.ReactElement<ToggleButtonProps>, {
                    name,
                    activeKey,
                    onChange,
                })
            )}
        </div>
    )
}

function ToggleButton({ value, active, onChange, children, title }: ToggleButtonProps & { name?: string; activeKey?: string; onChange?: (value: string) => void }) {
    const handleClick = () => onChange?.(value)
    return (
        <button
            className={`toggle-button${active ? ' active' : ''}`}
            onClick={handleClick}
            title={title}
            type="button"
        >
            {children}
        </button>
    )
}



const CLASS_LABELS = [
    'Unlabeled',
    'Label Class 1', 'Label Class 2', 'Label Class 3',
    'Label Class 4', 'Label Class 5', 'Label Class 6',
    'Label Class 7', 'Label Class 8', 'Label Class 9',
]

const CLASS_COLORS = [
    '#222222',  // Unlabeled
    '#e41a1c',  // Class 1
    '#377eb8',  // Class 2
    '#ff7f00',  // Class 3
    '#984ea3',  // Class 4
    '#4daf4a',  // Class 5
    '#ffff33',  // Class 6
    '#a65628',  // Class 7
    '#f781bf',  // Class 8
    '#999999',  // Class 9
]

const NUM_CLASSES = CLASS_LABELS.length

function makeAllCells(): Set<string> {
    const s = new Set<string>()
    for (let gt = 0; gt < NUM_CLASSES; gt++)
        for (let pred = 0; pred < NUM_CLASSES; pred++)
            s.add(`${gt},${pred}`)
    return s
}



export default function LabelingPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>()
    const projectId = Number(projectIdParam)
    const [colorBy, setColorBy] = useState<string>('gt')
    const [filterBy, setFilterBy] = useState<string>('all')
    const [selectedCells, setSelectedCells] = useState<Set<string>>(makeAllCells)
    const [cmPinned, setCmPinned] = useState<boolean>(true)
    const [bounds, setBounds] = useState<MapBounds | null>(null)
    const [zoomInfo, setZoomInfo] = useState<string>('')
    const [worldInfo, setWorldInfo] = useState<WorldInfo | null>(null)
    const [refreshTick, setRefreshTick] = useState(0)
    const [refreshIntervalMs, setRefreshIntervalMs] = useState<number | null>(5000)
    const [polygonTool, setPolygonTool] = useState(false)
    const [patchGalleryItems, setPatchGalleryItems] = useState<PatchResponse[] | null>(null)
    const [pageSize, setPageSize] = useState(24)

    useEffect(() => {
        infoProjectsProjectIdInfoGet({ path: { project_id: projectId } })
            .then(({ data, error }) => {
                if (data) setWorldInfo(data)
                else console.error('Error fetching world info:', error)
            })
            .catch(err => console.error('Error fetching world info:', err))
    }, [])

    const lp = useMemo(() => {
        const pairs = Array.from(selectedCells).sort()
        if ((filterBy !== 'all' || selectedCells.size < NUM_CLASSES * NUM_CLASSES)
            && pairs.length > 0 && pairs.length < NUM_CLASSES * NUM_CLASSES)
            return pairs
        return undefined
    }, [selectedCells, filterBy])

    const { data: confusionData = null } = useQuery<ConfusionData | null>({
        queryKey: ['confusionMatrix', bounds, lp, refreshTick],
        queryFn: () => getConfusionMatrixProjectsProjectIdConfusionMatrixGet({
            path: { project_id: projectId },
            query: {
                x_min: bounds!.left,
                y_min: bounds!.top,
                x_max: bounds!.right,
                y_max: bounds!.bottom,
                lp,
            }
        }).then(({ data, error }) => {
            if (error) throw error
            return data ?? null
        }),
        enabled: bounds !== null,
        staleTime: Infinity,
    })

    // ---- Selection helpers ----

    function applyFilter(filter: string, currentSelected = selectedCells): Set<string> {
        const s = new Set<string>()
        if (filter === 'all') {
            for (let gt = 0; gt < NUM_CLASSES; gt++)
                for (let pred = 0; pred < NUM_CLASSES; pred++)
                    s.add(`${gt},${pred}`)
        } else if (filter === 'concordant') {
            for (let i = 0; i < NUM_CLASSES; i++) s.add(`${i},${i}`)
        } else if (filter === 'discordant') {
            for (let gt = 0; gt < NUM_CLASSES; gt++)
                for (let pred = 0; pred < NUM_CLASSES; pred++)
                    if (gt !== pred) s.add(`${gt},${pred}`)
        } else {
            // custom — keep current
            return currentSelected
        }
        return s
    }

    function ensureNonEmpty(s: Set<string>): { cells: Set<string>; filter: string } {
        if (s.size > 0) return { cells: s, filter: 'custom' }
        const cells = makeAllCells()
        return { cells, filter: 'all' }
    }

    // ---- Event handlers ----

    function handleCellClick(gt: number, pred: number, multiSelect: boolean) {
        setSelectedCells(prev => {
            const key = `${gt},${pred}`
            const next = new Set(prev)
            if (multiSelect) {
                if (next.has(key)) next.delete(key); else next.add(key)
            } else {
                next.clear(); next.add(key)
            }
            const { cells, filter } = ensureNonEmpty(next)
            setFilterBy(filter)
            return cells
        })
    }

    function handleHeaderClick(axis: 'gt' | 'pred', index: number, multiSelect: boolean) {
        setSelectedCells(prev => {
            const keysToToggle: string[] = []
            for (let i = 0; i < NUM_CLASSES; i++) {
                keysToToggle.push(axis === 'gt' ? `${index},${i}` : `${i},${index}`)
            }
            const next = new Set(prev)
            if (multiSelect) {
                const allSelected = keysToToggle.every(k => next.has(k))
                if (allSelected) keysToToggle.forEach(k => next.delete(k))
                else keysToToggle.forEach(k => next.add(k))
            } else {
                next.clear(); keysToToggle.forEach(k => next.add(k))
            }
            const { cells, filter } = ensureNonEmpty(next)
            setFilterBy(filter)
            return cells
        })
    }

    function handleFilterChange(value: string) {
        setFilterBy(value)
        if (value !== 'custom') {
            setSelectedCells(applyFilter(value))
        }
    }

    function handleReset() {
        setColorBy('gt')
        setFilterBy('all')
        setSelectedCells(makeAllCells())
    }

    function handleZoomChange(osmZoom: number, level: number) {
        setZoomInfo(`OSM zoom: ${osmZoom}  →  agg level: ${level}`)
    }

    function handleClear() {
        setPatchGalleryItems([])
    }

    async function handlePolygonComplete(bbox: { x_min: number; x_max: number; y_min: number; y_max: number }) {
        try {
            const res = await client.get({
                path: { project_id: projectId },
                query: {
                    x_min: bbox.x_min,
                    y_min: bbox.y_min,
                    x_max: bbox.x_max,
                    y_max: bbox.y_max,
                    limit: pageSize,
                },
                url: '/projects/{project_id}/patches/',
            })
            if (res.data && Array.isArray(res.data)) {
                setPatchGalleryItems(res.data as PatchResponse[])
            }
        } catch (err) {
            console.error('Failed to fetch patches by polygon bbox:', err)
        }
    }

    return (
        <div className="labeling-page">
            {/* Left column: map + overlays */}
            <div className="labeling-column labeling-column-map">
                <Viewport
                    projectId={projectId}
                    colorBy={colorBy}
                    filterBy={filterBy}
                    selectedCells={selectedCells}
                    numClasses={NUM_CLASSES}
                    worldInfo={worldInfo}
                    refreshTick={refreshTick}
                    onBoundsChange={setBounds}
                    onZoomChange={handleZoomChange}
                    polygonTool={polygonTool}
                    onPolygonComplete={handlePolygonComplete}
                    onClear={handleClear}
                />

                {/* OSM zoom info in bottom left */}
                <div id="zoom-info-floating">{zoomInfo}</div>

                {/* Left controls overlay: reset, color by, filter by (flattened) */}
                <div id="controls-left">
                    <div className="control-row flattened">
                        <button onClick={handleReset} style={{ alignSelf: 'end', height: 32, marginRight: 8 }}>Reset</button>
                        <div className="control-group">
                            <label>Color scatter plot by</label>
                            <select value={colorBy} onChange={e => setColorBy(e.target.value)}>
                                <option value="gt">Ground Truth</option>
                                <option value="pred">Prediction</option>
                            </select>
                        </div>
                        <div className="control-group">
                            <label>Filter by</label>
                            <select value={filterBy} onChange={e => handleFilterChange(e.target.value)}>
                                <option value="all">All</option>
                                <option value="discordant">Discordant</option>
                                <option value="concordant">Concordant</option>
                                <option value="custom">Custom</option>
                            </select>
                        </div>
                        <div className="control-group">
                            <label>Polygon tool</label>
                            <ToggleButtonGroup
                                name="polygonTool"
                                activeKey={polygonTool ? 'on' : 'off'}
                                onChange={val => setPolygonTool(val === 'on')}
                            >
                                <ToggleButton value="off" active={!polygonTool} title="Click and drag on the map to draw a polygon">
                                    <span className="toggle-icon">○</span>
                                    <span className="toggle-label">Off</span>
                                </ToggleButton>
                                <ToggleButton value="on" active={polygonTool} title="Click to add points, double-click to complete">
                                    <span className="toggle-icon">⬠</span>
                                    <span className="toggle-label">On</span>
                                </ToggleButton>
                            </ToggleButtonGroup>
                        </div>
                        <RefreshTimer
                            intervalMs={refreshIntervalMs}
                            onIntervalChange={setRefreshIntervalMs}
                            onTick={() => setRefreshTick(t => t + 1)}
                        />
                    </div>
                </div>

                {/* Right controls overlay: pin + confusion matrix */}
                <div id="controls-right">
                    <div className={`cm-wrapper${cmPinned ? ' pinned' : ''}`}>
                        <label className="cm-pin-label">
                            <input
                                type="checkbox"
                                checked={cmPinned}
                                onChange={e => setCmPinned(e.target.checked)}
                            />
                            Pin Confusion Matrix
                        </label>
                        <div className="cm-content">
                            <ConfusionMatrix
                                confusionData={confusionData}
                                selectedCells={selectedCells}
                                colorBy={colorBy}
                                classLabels={CLASS_LABELS}
                                classColors={CLASS_COLORS}
                                onCellClick={handleCellClick}
                                onHeaderClick={handleHeaderClick}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* Right column: patch gallery */}
            <div className="labeling-column labeling-column-gallery">
                <PatchGallery projectId={projectId} patchGalleryItems={patchGalleryItems} pageSize={pageSize} setPageSize={setPageSize} />
            </div>
        </div>
    )
}
