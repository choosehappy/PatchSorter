import { useEffect, useRef, useState } from 'react'
import { client } from '../api_client/client.gen'
import { type ServeTileProjectsProjectIdTilesZxyPngGetData, type GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData, type WorldInfo, type PatchResponse, type LabelClassResponse, listPatchesProjectsProjectIdPatchesGet } from '../api_client'

interface PatchResponseGroup extends Array<PatchResponse> {
    query_bbox: { x_min: number; y_min: number; x_max: number; y_max: number }
}

// GeoJS loaded via CDN in index.html
declare const geo: any

import { WORLD_SIZE, QUAD_HALF } from '../constants'

export interface MapBounds {
    left: number
    right: number
    top: number
    bottom: number
}

interface ViewportProps {
    projectId: number
    colorBy: string
    filterBy: string
    selectedCells: Set<string>
    numClasses: number
    classIds: number[]
    worldInfo: WorldInfo | null
    refreshTick: number
    onBoundsChange: (bounds: MapBounds) => void
    onZoomChange: (osmZoom: number, level: number) => void
    onLassoComplete: (polygon: number[][], pageSize: number) => void
    onViewportClick: () => void
    onHoverPatch: (patch: PatchResponse | null) => void
    pageSize: number
    selectedPatches: PatchResponse[]
    hoveredPatch: PatchResponse | null
    showPatches: boolean
    queryRange: number
    numSamples: number
    labelClasses: LabelClassResponse[]
}

export default function Viewport({
    projectId,
    colorBy,
    filterBy,
    selectedCells,
    numClasses,
    classIds,
    worldInfo,
    refreshTick,
    onBoundsChange,
    onZoomChange,
    onLassoComplete,
    onViewportClick,
    onHoverPatch,
    pageSize,
    selectedPatches,
    hoveredPatch,
    showPatches,
    queryRange,
    numSamples,
    labelClasses,
}: ViewportProps) {
    const osmZoomOffset = worldInfo?.osm_zoom_offset ?? 8
    const maxOsmZoom = (worldInfo?.max_level ?? 12) - osmZoomOffset
    const mapDivRef = useRef<HTMLDivElement>(null)
    const mapRef = useRef<any>(null)
    const overlayLayerRef = useRef<any>(null)
    const paramsRef = useRef<any>(null)
    const annotationLayerRef = useRef<any>(null)
    const featureLayerRef = useRef<any>(null)
    const pointLayerRef = useRef<any>(null)
    const pointFeatureRef = useRef<any>(null)
    const patchLayerRef = useRef<any>(null)
    const patchFeatureRef = useRef<any>(null)
    const quadLayerRef = useRef<any>(null)
    const quadFeatureRef = useRef<any>(null)
    const clickQuadFeatureRef = useRef<any>(null)
    const queryBboxLayerRef = useRef<any>(null)
    const queryBboxFeatureRef = useRef<any>(null)
    const clickQueryBboxFeatureRef = useRef<any>(null)
    const isDrawingRef = useRef(false)
    const justCompletedRef = useRef(false)
    const isCtrlHeldRef = useRef(false)
    const bboxAbortRef = useRef<AbortController | null>(null)
    const [isCtrlHeld, setIsCtrlHeld] = useState(false)

    const queryRangeRef = useRef(queryRange)
    queryRangeRef.current = queryRange

    function buildLpQuery() {
        if (filterBy !== 'all' || selectedCells.size < numClasses * numClasses) {
            const pairs = Array.from(selectedCells)
            if (pairs.length > 0 && pairs.length < numClasses * numClasses && classIds.length === numClasses) {
                return pairs.map(p => {
                    const [gtIdx, predIdx] = p.split(',').map(Number)
                    return `${classIds[gtIdx]},${classIds[predIdx]}`
                })
            }
        }
        return undefined
    }

    function computeBboxFromPolygon(coordinates: number[][][]): { x_min: number; x_max: number; y_min: number; y_max: number } | null {
        const ring = coordinates[0]
        let wxMin = Infinity, wxMax = -Infinity, wyMin = Infinity, wyMax = -Infinity
        for (const [x, y] of ring) {
            if (x < wxMin) wxMin = x
            if (x > wxMax) wxMax = x
            if (y < wyMin) wyMin = y
            if (y > wyMax) wyMax = y
        }
        if (wxMin < wxMax && wyMin < wyMax) {
            return { x_min: wxMin, x_max: wxMax, y_min: wyMin, y_max: wyMax }
        }
        return null
    }

    function createLassoFeature(layer: any, coordinates: number[][][]) {
        const feature = layer.createFeature('polygon')
        feature.props = { type: 'lasso' }

        feature
            .position((d: number[][]) => ({ x: d[0], y: d[1] }))
            .polygon((a: number[][][]) => ({
                outer: a[0],
                inner: a.slice(1)
            }))
            .data([coordinates])
            .style('fill', true)
            .style('fillColor', 'rgba(0, 165, 255, 0.3)')
            .style('fillOpacity', 0.3)
            .style('strokeColor', 'blue')
            .style('strokeWidth', 2)
            .style('stroke', true)
            .style('uniformPolygon', true)

        const originalDraw = feature.draw
        feature.draw = function () {
            originalDraw.call(this)
            return this
        }

        feature.draw()

        return feature
    }

    function handleNewAnnotation(e: any) {
        if (e.annotation?.state() !== geo.annotation.state.done) return
        isDrawingRef.current = false
        justCompletedRef.current = true

        // Get coordinates from the newly created annotation
        const annotation = e.annotation
        const geometry = annotation?.geojson()?.geometry
        const coordinates: number[][][] | null = geometry?.type === 'Polygon' ? geometry.coordinates : null
        if (!coordinates || coordinates.length === 0) return

        const bbox = computeBboxFromPolygon(coordinates)
        if (bbox) {
            onLassoComplete(coordinates[0], pageSize)
        }

        // Add the polygon as a feature in the feature layer
        createLassoFeature(featureLayerRef.current, coordinates)

        // Keep annotation visible; restore drawing mode for next lasso
        annotationLayerRef.current.mode('polygon')
        annotationLayerRef.current.draw()
    }

    function toggleLassoMode(isOn: boolean) {
        if (!annotationLayerRef.current || !mapRef.current) return
        if (isOn) {
            annotationLayerRef.current.mode('polygon', undefined, {
                createStyle: {
                    fillColor: 'rgba(255, 165, 0, 0.3)',
                    strokeColor: 'orange',
                    strokeWidth: 2,
                    pointSize: 5,
                    pointFillColor: 'orange',
                    pointBorderColor: 'darkorange',
                    pointBorderWidth: 1,
                },
            })
        } else {
            annotationLayerRef.current.mode(null)
        }
        annotationLayerRef.current.draw()
    }

    // Keep a mutable ref for tile-URL state so the GeoJS callback always reads
    // the latest values without needing to re-register it.
    const tileStateRef = useRef({ colorBy, filterBy, selectedCells, numClasses, classIds })
    tileStateRef.current = { colorBy, filterBy, selectedCells, numClasses, classIds }

    const cacheKeyRef = useRef(Date.now())

    function buildPatchImageUrl(patchId: number): string {
        const options = {
            path: { project_id: projectId, patch_id: patchId },
            url: '/projects/{project_id}/patches/{patch_id}/image' satisfies GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData['url'],
        } as GetPatchImageProjectsProjectIdPatchesPatchIdImageGetData

        return client.buildUrl(options)
    }

    function buildTileUrl(x: number, y: number, z: number): string {
        const { colorBy, filterBy, selectedCells, numClasses, classIds } = tileStateRef.current
        const sumOver = colorBy !== 'gt' ? 'gt' : 'pred'
        const bounds = mapRef.current.bounds()

        const tile_url = '/projects/{project_id}/tiles/{z}/{x}/{y}.png' satisfies ServeTileProjectsProjectIdTilesZxyPngGetData['url']

        const query: Record<string, any> = {
            sum_over: sumOver,
            vp_x_min: bounds.left,
            vp_y_min: bounds.top,
            vp_x_max: bounds.right,
            vp_y_max: bounds.bottom,
            _t: cacheKeyRef.current,
        }

        if (filterBy !== 'all' || selectedCells.size < numClasses * numClasses) {
            const pairs = Array.from(selectedCells)
            if (pairs.length > 0 && pairs.length < numClasses * numClasses && classIds.length === numClasses) {
                query.lp = pairs.map(p => {
                    const [gtIdx, predIdx] = p.split(',').map(Number)
                    return `${classIds[gtIdx]},${classIds[predIdx]}`
                })
            }
        }

        const options = {
            path: { z, x, y, project_id: projectId },
            query,
            url: tile_url
        } as ServeTileProjectsProjectIdTilesZxyPngGetData

        return client.buildUrl(options)
    }

    function rebuildLayer() {
        if (!mapRef.current || !paramsRef.current) return
        if (overlayLayerRef.current) {
            mapRef.current.deleteLayer(overlayLayerRef.current)
        }
        paramsRef.current.layer.url = (x: number, y: number, z: number) => buildTileUrl(x, y, z)
        overlayLayerRef.current = mapRef.current.createLayer('osm', { ...paramsRef.current.layer, zIndex: 0 })
        mapRef.current.draw()
    }

    function getWorldUnitsPerPixel(): number {
        const origin = mapRef.current.displayToWorld({ x: 0, y: 0 })
        const onePixel = mapRef.current.displayToWorld({ x: 1, y: 0 })
        return onePixel.x - origin.x
    }

    function bboxToRing(xMin: number, yMin: number, xMax: number, yMax: number): number[][] {
        return [
            [xMin, yMin],
            [xMax, yMin],
            [xMax, yMax],
            [xMin, yMax],
            [xMin, yMin],
        ]
    }

    function buildQuadData(groups: PatchResponseGroup[]) {
        const scaled_half = QUAD_HALF * getWorldUnitsPerPixel()
        const result: { ul: { x: number; y: number }; lr: { x: number; y: number }; image: string }[] = []
        for (const group of groups) {
            const anchorI = group.query_bbox.x_max
            const anchorJ = group.query_bbox.y_max
            for (let i = 0; i < group.length; i++) {
                const p = group[i]
                const col = i % 3
                const row = Math.floor(i / 3)
                result.push({
                    ul: { x: anchorI + col * 2 * scaled_half, y: anchorJ + row * 2 * scaled_half },
                    lr: { x: anchorI + (col + 1) * 2 * scaled_half, y: anchorJ + (row + 1) * 2 * scaled_half },
                    image: buildPatchImageUrl(p.patch_id),
                })
            }
        }
        return result
    }

    function renderPatchData(groups: PatchResponseGroup[]) {
        const flat = groups.flatMap(g => g)

        if (patchLayerRef.current && patchFeatureRef.current) {
            patchLayerRef.current.deleteFeature(patchFeatureRef.current)
            patchFeatureRef.current = patchLayerRef.current
                .createFeature('point', { primitiveShape: 'circle' })
                .data(flat)
                .position((p: PatchResponse) => ({ x: p.grid_cell_i!, y: p.grid_cell_j! }))
                .style('fillColor', (p: PatchResponse) => {
                    if (p.label_class_id != null) {
                        const lc = labelClasses.find(l => l.label_class_id === p.label_class_id)
                        return lc?.color_code ?? '#888888'
                    }
                    return '#888888'
                })
                .style('fillOpacity', 0.6)
                .style('radius', 3)
                .style('stroke', false)
            patchLayerRef.current.draw()
        }

        if (quadLayerRef.current && quadFeatureRef.current) {
            quadLayerRef.current.deleteFeature(quadFeatureRef.current)
            quadFeatureRef.current = quadLayerRef.current
                .createFeature('quad')
                .data(buildQuadData(groups))
            quadLayerRef.current.draw()
        }
    }

    function sampleAndRenderProgressive(
        bounds: MapBounds,
        lp: string[] | undefined,
        signal: AbortSignal,
    ) {
        const accumulated: PatchResponseGroup[] = []
        let pendingFlush = false

        const width = bounds.right - bounds.left;
        const height = bounds.bottom - bounds.top;
        const aspectRatio = width / height;
        const rawCols = Math.sqrt(numSamples * aspectRatio);
        const rawRows = numSamples / rawCols;
        const PATCH_GRID_COLS = Math.max(1, Math.round(rawCols));
        const PATCH_GRID_ROWS = Math.max(1, Math.round(rawRows));

        const points = Array.from({ length: PATCH_GRID_ROWS * PATCH_GRID_COLS }, (_, i) => {
            const row = Math.floor(i / PATCH_GRID_COLS);
            const col = i % PATCH_GRID_COLS;

            return {
                x: bounds.left + ((col + 0.5) / PATCH_GRID_COLS) * width,
                y: bounds.top + ((row + 0.5) / PATCH_GRID_ROWS) * height,
            };
        });

        function flush() {
            if (signal.aborted) return
            pendingFlush = false
            renderPatchData(accumulated)
        }

        function scheduleFlush() {
            if (pendingFlush) return
            pendingFlush = true
            requestAnimationFrame(flush)
        }
        // const worldUnitsPerPixel = getWorldUnitsPerPixel()
        const halfRange = Math.floor(queryRange / 2)
        const bboxRings: number[][][] = points.map(({ x, y }) =>
            bboxToRing(x - halfRange, y - halfRange, x + halfRange, y + halfRange)
        )
        queryBboxFeatureRef.current?.data(bboxRings).modified()
        queryBboxLayerRef.current?.draw()
        const query_bbox = {
            x_min: Infinity,
            y_min: Infinity,
            x_max: -Infinity,
            y_max: -Infinity,
        }
        points.forEach(({ x, y }) => {
            const x_min = x - halfRange
            const y_min = y - halfRange
            const x_max = x + halfRange
            const y_max = y + halfRange
            if (x_min < query_bbox.x_min) query_bbox.x_min = x_min
            if (y_min < query_bbox.y_min) query_bbox.y_min = y_min
            if (x_max > query_bbox.x_max) query_bbox.x_max = x_max
            if (y_max > query_bbox.y_max) query_bbox.y_max = y_max
            listPatchesProjectsProjectIdPatchesGet({
                client,
                path: { project_id: projectId },
                query: { x_min: x_min, y_min: y_min, x_max: x_max, y_max: y_max, lp, limit: 9 },
                signal,
            })
                .then(({ data }) => {
                    if (signal.aborted) return
                    if (!data || data.length === 0) return
                    const group = data as PatchResponseGroup
                    group.query_bbox = { x_min: x_min, y_min: y_min, x_max: x_max, y_max: y_max }
                    accumulated.push(group)
                    scheduleFlush()
                })
                .catch((err) => {
                    if (err?.name !== 'AbortError') console.error('[sample] fetch error:', err)
                })
        })
    }

    // Initialise the GeoJS map once the div is mounted
    useEffect(() => {
        if (!mapDivRef.current) return

        const params = geo.util.pixelCoordinateParams(
            mapDivRef.current, WORLD_SIZE, WORLD_SIZE, WORLD_SIZE / 2, WORLD_SIZE / 2
        )
        params.map.zoom = 0
        params.map.minZoom = 0
        params.map.max = maxOsmZoom
        params.map.center = { x: WORLD_SIZE / 2, y: WORLD_SIZE / 2 }
        paramsRef.current = params

        const map = geo.map(params.map)
        mapRef.current = map

        // Resize map when container div changes size (e.g. split divider drag)
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect
                map.size({ width, height })
            }
        })
        resizeObserver.observe(mapDivRef.current)

        // Disable rotation interactions
        const interactor = map.interactor()
        interactor.removeAction(geo.geo_action.rotate, 'button rotate')
        interactor.removeAction(geo.geo_action.rotate, 'wheel rotate')

        // Disable keyboard zoom hotkeys to prevent conflicts with annotation tools
        const keyboardOptions = interactor.keyboard()
        keyboardOptions.actions['zoom.0'] = []
        keyboardOptions.actions['zoom.3'] = []
        keyboardOptions.actions['zoom.6'] = []
        keyboardOptions.actions['zoom.9'] = []
        keyboardOptions.actions['zoom.12'] = []
        keyboardOptions.actions['zoom.15'] = []
        keyboardOptions.actions['zoom.18'] = []
        interactor.keyboard(keyboardOptions)

        params.layer.url = (x: number, y: number, z: number) => buildTileUrl(x, y, z)
        params.layer.nearestPixel = true
        params.layer.background = { r: 1, g: 1, b: 1, a: 1 }
        params.layer.maxLevel = maxOsmZoom
        overlayLayerRef.current = map.createLayer('osm', { ...params.layer, zIndex: 0 })

        // Create annotation layer on init
        annotationLayerRef.current = map.createLayer('annotation', {
            zIndex: 1,
            finalPointProximity: 1000,
            continuousCloseProximity: true,
        })

        // Create feature layer for lasso polygons
        featureLayerRef.current = map.createLayer('feature', {
            zIndex: 2,
        })

        // Create point layer for selected/hovered patches
        pointLayerRef.current = map.createLayer('feature', {
            zIndex: 3,
        })
        pointFeatureRef.current = pointLayerRef.current
            .createFeature('point', { primitiveShape: 'circle' })
            .data([])
            .position((p: PatchResponse) => ({ x: p.grid_cell_i!, y: p.grid_cell_j! }))
            .style('radius', 5)
            .style('fillColor', '#ff4444')
            .style('fillOpacity', 0.9)
            .style('stroke', true)
            .style('strokeColor', 'white')
            .style('strokeWidth', 1.5)
        pointLayerRef.current.draw()
        toggleLassoMode(true)

        // Create patch layer for all patches (shown/hidden by showPatches toggle)
        patchLayerRef.current = map.createLayer('feature', {
            zIndex: 2,
        })
        patchFeatureRef.current = patchLayerRef.current
            .createFeature('point', { primitiveShape: 'circle' })
            .data([])
            .position((p: PatchResponse) => ({ x: p.grid_cell_i!, y: p.grid_cell_j! }))
            .style('radius', 3)
            .style('fillColor', '#888888')
            .style('fillOpacity', 0.5)
            .style('stroke', false)
        patchLayerRef.current.draw()

        // Create quad layer for patch quads
        quadLayerRef.current = map.createLayer('feature', { zIndex: 2 })
        quadFeatureRef.current = quadLayerRef.current
            .createFeature('quad')
            .data([])

        // Create hover quad feature (independent of main quad feature)
        clickQuadFeatureRef.current = quadLayerRef.current
            .createFeature('quad')
            .data([])
        quadLayerRef.current.draw()

        // Create query bounding-box layer (mirrors quad layer structure)
        queryBboxLayerRef.current = map.createLayer('feature', { zIndex: 2.5 })
        queryBboxFeatureRef.current = queryBboxLayerRef.current
            .createFeature('polygon')
            .position((d: number[]) => ({ x: d[0], y: d[1] }))
            .polygon((a: number[][]) => ({ outer: a, inner: [] }))
            .data([])
            .style('fill', false)
            .style('stroke', true)
            .style('strokeColor', 'lime')
            .style('strokeWidth', 1)
            .style('strokeOpacity', 0.6)
        clickQueryBboxFeatureRef.current = queryBboxLayerRef.current
            .createFeature('polygon')
            .position((d: number[]) => ({ x: d[0], y: d[1] }))
            .polygon((a: number[][]) => ({ outer: a, inner: [] }))
            .data([])
            .style('fill', false)
            .style('stroke', true)
            .style('strokeColor', 'magenta')
            .style('strokeWidth', 1.5)
            .style('strokeOpacity', 0.9)
        queryBboxLayerRef.current.draw()

        // Register annotation completion event listener
        annotationLayerRef.current.geoOn(geo.event.annotation.state, handleNewAnnotation)

        // Remove lasso features on mousedown
        function handleMousedown() {
            featureLayerRef.current.clear()
            featureLayerRef.current.draw()
            onViewportClick()
        }
        featureLayerRef.current.geoOn(geo.event.mousedown, handleMousedown)

        function handleClick(evt: any) {
            const lp = buildLpQuery()
            const queryRangeVal = Math.max(2, Math.round(queryRangeRef.current))
            const halfRange = Math.floor(queryRangeVal / 2)

            const clickRing = bboxToRing(
                evt.geo.x - halfRange, evt.geo.y - halfRange,
                evt.geo.x + halfRange, evt.geo.y + halfRange
            )
            clickQueryBboxFeatureRef.current?.data([clickRing]).modified()
            queryBboxLayerRef.current?.draw()

            const x_min = evt.geo.x - halfRange
            const y_min = evt.geo.y - halfRange
            const x_max = evt.geo.x + halfRange
            const y_max = evt.geo.y + halfRange
            listPatchesProjectsProjectIdPatchesGet({
                client,
                path: { project_id: projectId },
                query: { x_min: x_min, y_min: y_min, x_max: x_max, y_max: y_max, lp: lp, limit: 9 },
            }).then(({ data, error }) => {
                if (error || !data || data.length === 0) {
                    clickQuadFeatureRef.current?.data([]).modified()
                    quadLayerRef.current?.draw()
                    onHoverPatch(null)
                    return
                }
                const group = data as PatchResponseGroup
                group.query_bbox = { x_min, y_min, x_max, y_max }
                clickQuadFeatureRef.current.data(buildQuadData([group])).modified()
                quadLayerRef.current.draw()
                onHoverPatch(data[0])
            }).catch(err => {
                clickQuadFeatureRef.current?.data([]).modified()
                quadLayerRef.current?.draw()
                console.error('[sampleByPoint] fetch error:', err)
                onHoverPatch(null)
            })
        }

        map.geoOn(geo.event.mouseclick, handleClick)

        map.geoOn(geo.event.zoom, () => {
            const z = Math.round(map.zoom())
            onZoomChange(z, z + osmZoomOffset)
        })
        map.geoTrigger(geo.event.zoom)

        let idleTimeout: ReturnType<typeof setTimeout> | null = null
        function onMapIdle() {
            if (idleTimeout) clearTimeout(idleTimeout)
            idleTimeout = setTimeout(() => {
                onBoundsChange(map.bounds())
            }, 200)
        }
        map.geoOn(geo.event.pan, onMapIdle)

        onBoundsChange(map.bounds())

        // Track Ctrl key state via mouse events on the map div
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Control') {
                isCtrlHeldRef.current = true
                setIsCtrlHeld(true)
            }
        }
        const handleKeyUp = (e: KeyboardEvent) => {
            if (e.key === 'Control') {
                isCtrlHeldRef.current = false
                setIsCtrlHeld(false)
            }
        }

        document.addEventListener('keydown', handleKeyDown)
        document.addEventListener('keyup', handleKeyUp)

        return () => {
            resizeObserver.disconnect()
            clickQuadFeatureRef.current?.data([]).modified()
            queryBboxFeatureRef.current?.data([]).modified()
            clickQueryBboxFeatureRef.current?.data([]).modified()
            annotationLayerRef.current?.geoOff(geo.event.annotation.state, handleNewAnnotation)
            featureLayerRef.current?.geoOff(geo.event.mousedown, handleMousedown)
            map.geoOff(geo.event.mouseclick, handleClick)
            map.geoOff(geo.event.zoom)
            map.geoOff(geo.event.pan, onMapIdle)
            document.removeEventListener('keydown', handleKeyDown)
            document.removeEventListener('keyup', handleKeyUp)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Refresh tile cache on every tick driven by the parent timer
    useEffect(() => {
        if (!overlayLayerRef.current) return
        cacheKeyRef.current = Date.now()
        overlayLayerRef.current.url((x: number, y: number, z: number) => buildTileUrl(x, y, z))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [refreshTick])

    // Rebuild layer when filter/colour state changes
    useEffect(() => {
        if (mapRef.current) rebuildLayer()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [colorBy, filterBy, selectedCells])

    // Change annotation mode based on Ctrl state
    useEffect(() => {
        if (isCtrlHeld) {
            toggleLassoMode(true)
        } else {
            toggleLassoMode(false)
        }
    }, [isCtrlHeld])

    // Update point layer whenever selected patches or hovered patch changes
    useEffect(() => {
        if (!pointFeatureRef.current) return
        const withCentroid = selectedPatches.filter(
            p => p.grid_cell_i != null && p.grid_cell_j != null
        )
        const hoveredId = hoveredPatch?.patch_id ?? null
        const extra =
            hoveredPatch &&
            hoveredPatch.grid_cell_i != null &&
            hoveredPatch.grid_cell_j != null &&
            !withCentroid.some(p => p.patch_id === hoveredPatch.patch_id)
                ? [hoveredPatch]
                : []
        const data = [...withCentroid, ...extra]
        console.debug('[pointLayer] data length:', data.length, data[0] && { cx: data[0].grid_cell_i, cy: data[0].grid_cell_j })
        const feat = pointFeatureRef.current
        feat.data(data)
        feat.style('radius', (p: PatchResponse) => p.patch_id === hoveredId ? 9 : 5)
        feat.style('fillColor', (p: PatchResponse) => p.patch_id === hoveredId ? '#000000' : '#000000')
        feat.modified()
        pointLayerRef.current.draw()
    }, [selectedPatches, hoveredPatch])

    // Fetch and render all patches when showPatches is toggled on
    useEffect(() => {
        if (!showPatches || !mapRef.current) {
            if (patchFeatureRef.current) {
                patchFeatureRef.current.data([])
                patchLayerRef.current?.draw()
            }
            if (quadFeatureRef.current) {
                quadFeatureRef.current.data([])
                quadLayerRef.current?.draw()
            }
            queryBboxFeatureRef.current?.data([]).modified()
            queryBboxLayerRef.current?.draw()
            return
        }

        const bounds = mapRef.current.bounds()

        const lp = buildLpQuery()

        bboxAbortRef.current?.abort()
        bboxAbortRef.current = new AbortController()
        const signal = bboxAbortRef.current.signal

        sampleAndRenderProgressive(bounds, lp, signal)

        let panZoomClearTimeout: ReturnType<typeof setTimeout> | null = null
        function onZoomStart() {
            if (quadFeatureRef.current) {
                quadFeatureRef.current.data([])
                quadLayerRef.current?.draw()
            }
            queryBboxFeatureRef.current?.data([]).modified()
            queryBboxLayerRef.current?.draw()
            if (panZoomClearTimeout) clearTimeout(panZoomClearTimeout)
            panZoomClearTimeout = setTimeout(async () => {
                if (!mapRef.current || !quadFeatureRef.current || !quadLayerRef.current) return
                const bounds = mapRef.current.bounds()
                const lp = buildLpQuery()
                bboxAbortRef.current?.abort()
                bboxAbortRef.current = new AbortController()
                const sig = bboxAbortRef.current.signal
                sampleAndRenderProgressive(bounds, lp, sig)
            }, 200)
        }
        mapRef.current.geoOn(geo.event.zoom, onZoomStart)
        mapRef.current.geoOn(geo.event.pan, onZoomStart)

        return () => {
            mapRef.current.geoOff(geo.event.zoom, onZoomStart)
            mapRef.current.geoOff(geo.event.pan, onZoomStart)
            bboxAbortRef.current?.abort()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [showPatches, projectId, selectedCells, queryRange, numSamples])

    // Update patch layer bounds when map bounds change
    useEffect(() => {
        if (!showPatches || !patchFeatureRef.current) return

        const interval = setInterval(() => {
            if (!mapRef.current) {
                clearInterval(interval)
                return
            }
            const bounds = mapRef.current.bounds()
            patchFeatureRef.current.style('fillColor', (p: PatchResponse) => {
                if (p.grid_cell_i != null && p.grid_cell_j != null) {
                    if (p.grid_cell_i >= bounds.left && p.grid_cell_i <= bounds.right &&
                        p.grid_cell_j >= bounds.top && p.grid_cell_j <= bounds.bottom) {
                        if (p.label_class_id != null) {
                            const lc = labelClasses.find(l => l.label_class_id === p.label_class_id)
                            return lc?.color_code ?? '#888888'
                        }
                        return '#888888'
                    }
                }
                return '#cccccc'
            })
            patchFeatureRef.current.modified()
            patchLayerRef.current?.draw()
        }, 500)

        return () => clearInterval(interval)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [showPatches])

    return <div ref={mapDivRef} style={{ width: '100%', height: '100%' }} />
}
