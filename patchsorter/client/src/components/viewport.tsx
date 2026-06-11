import { useEffect, useRef, useState } from 'react'
import { client } from '../api_client/client.gen'
import { type ServeTileApiV1ProjectsProjectIdTilesZxyPngGetData, type WorldInfo, type PatchResponse, type LabelClassResponse, samplePatchesByBboxApiV1ProjectsProjectIdSampleByBboxPatchesGet, samplePatchesByPointApiV1ProjectsProjectIdSampleByPointPatchesGet } from '../api_client'

// GeoJS loaded via CDN in index.html
declare const geo: any

import { WORLD_SIZE, PATCH_NUM_SAMPLES, PATCH_QUERY_RANGE, QUAD_HALF, HOVER_TIMEOUT_MS } from '../constants'

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
    const isDrawingRef = useRef(false)
    const justCompletedRef = useRef(false)
    const isCtrlHeldRef = useRef(false)
    const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const bboxAbortRef = useRef<AbortController | null>(null)
    const [isCtrlHeld, setIsCtrlHeld] = useState(false)

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

    function buildTileUrl(x: number, y: number, z: number): string {
        const { colorBy, filterBy, selectedCells, numClasses, classIds } = tileStateRef.current
        const sumOver = colorBy !== 'gt' ? 'gt' : 'pred'
        const bounds = mapRef.current.bounds()

        const tile_url = '/api/v1/projects/{project_id}/tiles/{z}/{x}/{y}.png' satisfies ServeTileApiV1ProjectsProjectIdTilesZxyPngGetData['url']

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
        } as ServeTileApiV1ProjectsProjectIdTilesZxyPngGetData

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

    function renderPatchData(data: PatchResponse[], zoom: number) {
        if (patchFeatureRef.current) {
            patchFeatureRef.current.data(data)
            patchFeatureRef.current.style('fillColor', (p: PatchResponse) => {
                if (p.label_class_id != null) {
                    const lc = labelClasses.find(l => l.label_class_id === p.label_class_id)
                    return lc?.color_code ?? '#888888'
                }
                return '#888888'
            })
            patchFeatureRef.current.style('fillOpacity', 0.6)
            patchFeatureRef.current.style('radius', 3)
            patchFeatureRef.current.modified()
            patchLayerRef.current?.draw()
        }
        if (quadFeatureRef.current) {
            const half = QUAD_HALF * Math.pow(2, -zoom)
            quadFeatureRef.current.data(
                data
                    .filter(p => p.grid_cell_i != null && p.grid_cell_j != null)
                    .map(p => ({
                        ul: { x: p.grid_cell_i!, y: p.grid_cell_j! - 2 * half },
                        lr: { x: p.grid_cell_i! + 2 * half, y: p.grid_cell_j! },
                        image: `/api/v1/projects/${projectId}/patches/${p.patch_id}/image`,
                    }))
            )
            quadFeatureRef.current.modified()
            quadLayerRef.current?.draw()
        }
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
        quadLayerRef.current.draw()

        // Register annotation completion event listener
        annotationLayerRef.current.geoOn(geo.event.annotation.state, handleNewAnnotation)

        // Remove lasso features on mousedown
        function handleMousedown() {
            featureLayerRef.current.clear()
            featureLayerRef.current.draw()
            onViewportClick()
        }
        featureLayerRef.current.geoOn(geo.event.mousedown, handleMousedown)

        function handleMouseMove(evt: any) {
            if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current)
            hoverTimeoutRef.current = setTimeout(() => {
                const lp = buildLpQuery()

                samplePatchesByPointApiV1ProjectsProjectIdSampleByPointPatchesGet({
                    client,
                    path: { project_id: projectId },
                    query: { x: evt.geo.x, y: evt.geo.y, lp },
                }).then(({ data, error }) => {
                    if (error || !data || data.length === 0) {
                        onHoverPatch(null)
                        return
                    }
                    onHoverPatch(data[0])
                }).catch(err => {
                    console.error('[sampleByPoint] fetch error:', err)
                    onHoverPatch(null)
                })
            }, HOVER_TIMEOUT_MS)
        }

        map.geoOn(geo.event.mousemove, handleMouseMove)

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
            annotationLayerRef.current?.geoOff(geo.event.annotation.state, handleNewAnnotation)
            featureLayerRef.current?.geoOff(geo.event.mousedown, handleMousedown)
            map.geoOff(geo.event.mousemove, handleMouseMove)
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
            return
        }

        const bounds = mapRef.current.bounds()

        const lp = buildLpQuery()

        bboxAbortRef.current?.abort()
        bboxAbortRef.current = new AbortController()

        samplePatchesByBboxApiV1ProjectsProjectIdSampleByBboxPatchesGet({
            client,
            path: { project_id: projectId },
            query: {
                xmin: bounds.left,
                ymin: bounds.top,
                xmax: bounds.right,
                ymax: bounds.bottom,
                num_samples: PATCH_NUM_SAMPLES,
                patch_query_range: PATCH_QUERY_RANGE,
                lp,
            },
            signal: bboxAbortRef.current.signal,
        })
            .then(({ data, error }) => {
                if (error || !data) {
                    if (error?.name !== 'AbortError') {
                        console.error('[patchLayer] sample error:', error)
                    }
                    return
                }
                const zoom = Math.round(mapRef.current.zoom())
                renderPatchData(data, zoom)
            })
            .catch(err => {
                if (err.name !== 'AbortError') {
                    console.error('[patchLayer] fetch error:', err)
                }
            })

        let panZoomClearTimeout: ReturnType<typeof setTimeout> | null = null
        function onZoomStart() {
            if (quadFeatureRef.current) {
                quadFeatureRef.current.data([])
                quadLayerRef.current?.draw()
            }
            if (panZoomClearTimeout) clearTimeout(panZoomClearTimeout)
            panZoomClearTimeout = setTimeout(async () => {
                if (!mapRef.current || !quadFeatureRef.current || !quadLayerRef.current) return
                const zoom = Math.round(mapRef.current.zoom())
                const bounds = mapRef.current.bounds()
                const lp = buildLpQuery()
                bboxAbortRef.current?.abort()
                bboxAbortRef.current = new AbortController()
                const { data, error } = await samplePatchesByBboxApiV1ProjectsProjectIdSampleByBboxPatchesGet({
                    client,
                    path: { project_id: projectId },
                    query: {
                        xmin: bounds.left,
                        ymin: bounds.top,
                        xmax: bounds.right,
                        ymax: bounds.bottom,
                        num_samples: PATCH_NUM_SAMPLES,
                        patch_query_range: PATCH_QUERY_RANGE,
                        lp,
                    },
                    signal: bboxAbortRef.current.signal,
                })
                if (error || !data || data.length === 0) return
                renderPatchData(data, zoom)
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
    }, [showPatches, projectId, selectedCells])

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
