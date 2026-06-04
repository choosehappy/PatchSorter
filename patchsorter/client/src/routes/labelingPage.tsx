import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import './labelingPage.css'
import Viewport, { type MapBounds } from '../components/viewport'
import ConfusionMatrix, { type ConfusionData } from '../components/confusionMatrix'
import RefreshTimer from '../components/refreshTimer'
import PatchGallery from '../components/PatchGallery'
import LabelPicker from '../components/LabelPicker'
import { getConfusionMatrixProjectsProjectIdConfusionMatrixGet, infoProjectsProjectIdInfoGet, listLabelClassesProjectsProjectIdLabelClassesGet, listPatchesProjectsProjectIdPatchesGet, type LabelClassResponse, type PatchResponse, type WorldInfo } from '../api_client'



function makeAllCells(n: number): Set<string> {
    const s = new Set<string>()
    for (let gt = 0; gt < n; gt++)
        for (let pred = 0; pred < n; pred++)
            s.add(`${gt},${pred}`)
    return s
}



export default function LabelingPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>()
    const projectId = Number(projectIdParam)
    const [colorBy, setColorBy] = useState<string>('gt')
    const [filterBy, setFilterBy] = useState<string>('all')
    const [selectedCells, setSelectedCells] = useState<Set<string>>(() => new Set<string>())
    const [cmPinned, setCmPinned] = useState<boolean>(true)
    const [bounds, setBounds] = useState<MapBounds | null>(null)
    const [zoomInfo, setZoomInfo] = useState<string>('')
    const [worldInfo, setWorldInfo] = useState<WorldInfo | null>(null)
    const [refreshTick, setRefreshTick] = useState(0)
    const [refreshIntervalMs, setRefreshIntervalMs] = useState<number | null>(5000)
    const [pageSize, setPageSize] = useState(24)
    const [lassoPolygon, setLassoPolygon] = useState<number[][] | null>(null)
    const [activePage, setActivePage] = useState(0)
    const [selectedPatches, setSelectedPatches] = useState<PatchResponse[]>([])
    const [hoveredPatch, setHoveredPatch] = useState<PatchResponse | null>(null)
    const [showPicker, setShowPicker] = useState(false)
    const [pickedLabelClassId, setPickedLabelClassId] = useState<number | null>(null)

    useEffect(() => {
        infoProjectsProjectIdInfoGet({ path: { project_id: projectId } })
            .then(({ data, error }) => {
                if (data) setWorldInfo(data)
                else console.error('Error fetching world info:', error)
            })
            .catch(err => console.error('Error fetching world info:', err))
    }, [])

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Enter') {
                setShowPicker(true)
            }
        }
        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [])

    const handleLabelSelect = useCallback((labelClassId: number) => {
        setPickedLabelClassId(labelClassId)
    }, [])

    const { data: labelClassesData = [] } = useQuery<LabelClassResponse[]>({
        queryKey: ['labelClasses', projectId],
        queryFn: () => listLabelClassesProjectsProjectIdLabelClassesGet({ path: { project_id: projectId } })
            .then(({ data, error }) => {
                if (error) throw error
                return data ?? []
            }),
        staleTime: Infinity,
    })

    const sortedLabelClasses = useMemo(
        () => [...labelClassesData].sort((a, b) => a.label_class_id - b.label_class_id),
        [labelClassesData]
    )
    const classLabels = useMemo(() => sortedLabelClasses.map(lc => lc.name), [sortedLabelClasses])
    const classColors = useMemo(() => sortedLabelClasses.map(lc => lc.color_code ?? '#222222'), [sortedLabelClasses])
    const classIds = useMemo(() => sortedLabelClasses.map(lc => lc.label_class_id), [sortedLabelClasses])
    const numClasses = classLabels.length

    useEffect(() => {
        if (numClasses > 0) setSelectedCells(makeAllCells(numClasses))
    }, [numClasses])

    const lp = useMemo(() => {
        if (classIds.length === 0) return undefined
        const pairs = Array.from(selectedCells).sort()
        if ((filterBy !== 'all' || selectedCells.size < numClasses * numClasses)
            && pairs.length > 0 && pairs.length < numClasses * numClasses)
            return pairs.map(p => {
                const [gtIdx, predIdx] = p.split(',').map(Number)
                return `${classIds[gtIdx]},${classIds[predIdx]}`
            })
        return undefined
    }, [selectedCells, filterBy, classIds])

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

    const { data: galleryTotal = null } = useQuery<number | null>({
        queryKey: ['galleryTotal', projectId, lassoPolygon],
        queryFn: async () => {
            const bbox = computeBboxFromPolygon(lassoPolygon!)
            const { data, error } = await getConfusionMatrixProjectsProjectIdConfusionMatrixGet({
                path: { project_id: projectId },
                query: {
                    x_min: bbox.x_min,
                    y_min: bbox.y_min,
                    x_max: bbox.x_max,
                    y_max: bbox.y_max,
                },
            })
            if (error) throw error
            return data?.matrix
                ? (data.matrix as number[][]).flat().reduce((s, v) => s + v, 0)
                : null
        },
        enabled: lassoPolygon !== null,
        staleTime: Infinity,
    })

    const {
        data: patchesData,
        hasNextPage,
        fetchNextPage,
        isFetchingNextPage,
        isLoading: patchesLoading,
    } = useInfiniteQuery({
        queryKey: ['patches', projectId, lassoPolygon, pageSize, lp],
        queryFn: async ({ pageParam }: { pageParam: number }) => {
            const bbox = computeBboxFromPolygon(lassoPolygon!)
            const res = await listPatchesProjectsProjectIdPatchesGet({
                path: { project_id: projectId },
                query: {
                    cursor: pageParam,
                    limit: pageSize,
                    ...bbox,
                    lp,
                },
            })
            if (res.error) throw res.error
            return (res.data ?? []) as PatchResponse[]
        },
        initialPageParam: 0,
        getNextPageParam: (lastPage: PatchResponse[]) =>
            lastPage.length >= pageSize ? lastPage[lastPage.length - 1].patch_id : undefined,
        enabled: lassoPolygon !== null,
    })

    const currentPatches = patchesData?.pages[activePage] ?? []
    const totalPatches = galleryTotal
    const canGoNext = lassoPolygon !== null && (activePage < (patchesData?.pages.length ?? 0) - 1 || hasNextPage)
    const canGoPrev = lassoPolygon !== null && activePage > 0

    // ---- Selection helpers ----

    function applyFilter(filter: string, currentSelected = selectedCells): Set<string> {
        const s = new Set<string>()
        if (filter === 'all') {
            for (let gt = 0; gt < numClasses; gt++)
                for (let pred = 0; pred < numClasses; pred++)
                    s.add(`${gt},${pred}`)
        } else if (filter === 'concordant') {
            for (let i = 0; i < numClasses; i++) s.add(`${i},${i}`)
        } else if (filter === 'discordant') {
            for (let gt = 0; gt < numClasses; gt++)
                for (let pred = 0; pred < numClasses; pred++)
                    if (gt !== pred) s.add(`${gt},${pred}`)
        } else {
            // custom — keep current
            return currentSelected
        }
        return s
    }

    function ensureNonEmpty(s: Set<string>): { cells: Set<string>; filter: string } {
        if (s.size > 0) return { cells: s, filter: 'custom' }
        const cells = makeAllCells(numClasses)
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
            for (let i = 0; i < numClasses; i++) {
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
        setSelectedCells(makeAllCells(numClasses))
    }

    function handleZoomChange(osmZoom: number, level: number) {
        setZoomInfo(`OSM zoom: ${osmZoom}  →  agg level: ${level}`)
    }

    function handleClearLassoPolygon() {
        setLassoPolygon(null)
        setActivePage(0)
        setSelectedPatches([])
    }

    function handlePolygonPatchQuery(polygon: number[][], _pageSize: number) {
        setLassoPolygon(polygon)
        setActivePage(0)
        setSelectedPatches([])
    }

    async function handleNext() {
        if (activePage < (patchesData?.pages.length ?? 0) - 1) {
            setActivePage(p => p + 1)
        } else if (hasNextPage) {
            await fetchNextPage()
            setActivePage(p => p + 1)
        }
    }

    function handlePrev() {
        if (activePage > 0) setActivePage(p => p - 1)
    }

    function handlePageSizeChange(newSize: number) {
        setPageSize(newSize)
        setActivePage(0)
    }

    function computeBboxFromPolygon(ring: number[][]): { x_min: number; x_max: number; y_min: number; y_max: number } {
        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity
        for (const [x, y] of ring) {
            if (x < xMin) xMin = x
            if (x > xMax) xMax = x
            if (y < yMin) yMin = y
            if (y > yMax) yMax = y
        }
        return { x_min: xMin, x_max: xMax, y_min: yMin, y_max: yMax }
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
                    numClasses={numClasses}
                    classIds={classIds}
                    worldInfo={worldInfo}
                    refreshTick={refreshTick}
                    onBoundsChange={setBounds}
                    onZoomChange={handleZoomChange}
                    onLassoComplete={handlePolygonPatchQuery}
                    onViewportClick={handleClearLassoPolygon}
                    pageSize={pageSize}
                    selectedPatches={selectedPatches}
                    hoveredPatch={hoveredPatch}
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
                                classLabels={classLabels}
                                classColors={classColors}
                                classIds={classIds}
                                onCellClick={handleCellClick}
                                onHeaderClick={handleHeaderClick}
                            />
                        </div>
                    </div>
                </div>
            </div>

            {/* Right column: patch gallery */}
            <div className="labeling-column labeling-column-gallery">
                <PatchGallery
                    projectId={projectId}
                    patches={currentPatches}
                    isLoading={patchesLoading}
                    isFetchingNextPage={isFetchingNextPage}
                    canGoNext={canGoNext}
                    canGoPrev={canGoPrev}
                    onNext={handleNext}
                    onPrev={handlePrev}
                    pageSize={pageSize}
                    setPageSize={handlePageSizeChange}
                    totalPatches={totalPatches}
                    currentPage={activePage}
                    hasLasso={lassoPolygon !== null}
                    labelClasses={sortedLabelClasses}
                    selectedPatches={selectedPatches}
                    onSelectionChange={setSelectedPatches}
                    onHoverChange={setHoveredPatch}
                />
            </div>
            <LabelPicker
                isOpen={showPicker}
                labelClasses={sortedLabelClasses}
                onSelect={handleLabelSelect}
                onClose={() => setShowPicker(false)}
            />
        </div>
    )
}
