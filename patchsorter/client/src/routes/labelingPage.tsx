import { useState, useCallback } from 'react'
import './labelingPage.css'
import Viewport, { type MapBounds } from '../components/viewport'
import ConfusionMatrix, { type ConfusionData } from '../components/confusionMatrix'

const TILE_SERVER = ''

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
    const [colorBy, setColorBy] = useState<string>('gt')
    const [filterBy, setFilterBy] = useState<string>('all')
    const [selectedCells, setSelectedCells] = useState<Set<string>>(makeAllCells)
    const [confusionData, setConfusionData] = useState<ConfusionData | null>(null)
    const [zoomInfo, setZoomInfo] = useState<string>('')

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

    // ---- Confusion matrix fetch ----

    const fetchConfusionMatrix = useCallback(async (bounds: MapBounds) => {
        let url = `${TILE_SERVER}/confusion_matrix`
            + `?x_min=${bounds.left}&y_min=${bounds.top}`
            + `&x_max=${bounds.right}&y_max=${bounds.bottom}`

        // We read the latest filter state inline to avoid stale closure issues.
        // The actual selectedCells / filterBy values are captured from component state
        // at call time via the closure on each render that re-creates this callback.
        setSelectedCells(currentCells => {
            setFilterBy(currentFilter => {
                if (currentFilter !== 'all' || currentCells.size < NUM_CLASSES * NUM_CLASSES) {
                    const pairs = Array.from(currentCells)
                    if (pairs.length > 0 && pairs.length < NUM_CLASSES * NUM_CLASSES) {
                        pairs.forEach(pair => { url += `&lp=${pair}` })
                    }
                }
                // Side-effect fetch (safe — no setState in async path, we use setConfusionData separately)
                fetch(url)
                    .then(r => r.ok ? r.json() : Promise.reject(r.status))
                    .then((data: ConfusionData) => setConfusionData(data))
                    .catch(err => console.error('Error fetching confusion matrix:', err))
                return currentFilter  // no change
            })
            return currentCells  // no change
        })
    }, [])

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

    return (
        <div className="labeling-page">
            {/* Full-screen tile map */}
            <Viewport
                colorBy={colorBy}
                filterBy={filterBy}
                selectedCells={selectedCells}
                numClasses={NUM_CLASSES}
                onBoundsChange={fetchConfusionMatrix}
                onZoomChange={handleZoomChange}
            />

            {/* Controls overlay */}
            <div id="controls">
                <div className="header">
                    <button onClick={handleReset}>Reset</button>
                </div>

                <div className="control-row">
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
                </div>

                <ConfusionMatrix
                    confusionData={confusionData}
                    selectedCells={selectedCells}
                    colorBy={colorBy}
                    classLabels={CLASS_LABELS}
                    classColors={CLASS_COLORS}
                    onCellClick={handleCellClick}
                    onHeaderClick={handleHeaderClick}
                />

                <div id="zoom-info">{zoomInfo}</div>
            </div>
        </div>
    )
}
