import { useEffect, useRef, useState } from 'react'
import { client } from '../api_client/client.gen'
import { type ServeTileProjectsProjectIdTilesZxyPngGetData, type WorldInfo } from '../api_client'

// GeoJS loaded via CDN in index.html
declare const geo: any

import { WORLD_SIZE } from '../constants'

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
    worldInfo: WorldInfo | null
    refreshTick: number
    onBoundsChange: (bounds: MapBounds) => void
    onZoomChange: (osmZoom: number, level: number) => void
    onLassoComplete: (data: { polygon: number[][][]; bbox: { x_min: number; x_max: number; y_min: number; y_max: number } }) => void
    onViewportClick: () => void
}

export default function Viewport({
    projectId,
    colorBy,
    filterBy,
    selectedCells,
    numClasses,
    worldInfo,
    refreshTick,
    onBoundsChange,
    onZoomChange,
    onLassoComplete,
    onViewportClick,
}: ViewportProps) {
    const osmZoomOffset = worldInfo?.osm_zoom_offset ?? 8
    const maxOsmZoom = (worldInfo?.max_level ?? 12) - osmZoomOffset
    const mapDivRef = useRef<HTMLDivElement>(null)
    const mapRef = useRef<any>(null)
    const overlayLayerRef = useRef<any>(null)
    const paramsRef = useRef<any>(null)
    const annotationLayerRef = useRef<any>(null)
    const isDrawingRef = useRef(false)
    const justCompletedRef = useRef(false)
    const activeModeRef = useRef<'lasso' | 'polygon'>('lasso')
    const isCtrlHeldRef = useRef(false)
    const [isCtrlHeld, setIsCtrlHeld] = useState(false)

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

    function handleNewAnnotation(e: any) {
        if (e.type !== 'create') return
        isDrawingRef.current = false
        justCompletedRef.current = true

        // Get coordinates from the newly created annotation
        const annotation = e.annotation
        const geometry = annotation?.geojson()?.geometry
        const coordinates: number[][][] | null = geometry?.type === 'Polygon' ? geometry.coordinates : null
        if (!coordinates || coordinates.length === 0) return

        // Remove any previous polygon annotations, keeping only this new one
        const allAnnotations = annotationLayerRef.current.annotations()
        for (const ann of allAnnotations) {
            if (ann !== annotation) {
                annotationLayerRef.current.removeAnnotation(ann)
            }
        }

        const bbox = computeBboxFromPolygon(coordinates)
        if (bbox) {
            onLassoComplete({ polygon: coordinates, bbox })
        }

        // Keep annotation visible; restore drawing mode for next lasso
        annotationLayerRef.current.mode('lasso')
        annotationLayerRef.current.draw()
    }

    function setAnnotationMode(mode: 'lasso' | 'polygon') {
        if (!annotationLayerRef.current || !mapRef.current) return
        activeModeRef.current = mode
        annotationLayerRef.current.mode(mode, undefined, {
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
        annotationLayerRef.current.draw()
    }

    function clearLassoPolygon() {
        if (annotationLayerRef.current) {
            annotationLayerRef.current.removeAllAnnotations()
            annotationLayerRef.current.draw()
        }
        onViewportClick()
    }

    // Keep a mutable ref for tile-URL state so the GeoJS callback always reads
    // the latest values without needing to re-register it.
    const tileStateRef = useRef({ colorBy, filterBy, selectedCells, numClasses })
    tileStateRef.current = { colorBy, filterBy, selectedCells, numClasses }

    const cacheKeyRef = useRef(Date.now())

    function buildTileUrl(x: number, y: number, z: number): string {
        const { colorBy, filterBy, selectedCells, numClasses } = tileStateRef.current
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
            if (pairs.length > 0 && pairs.length < numClasses * numClasses) {
                query.lp = pairs
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
        annotationLayerRef.current = map.createLayer('annotation', { zIndex: 1 })
        setAnnotationMode('lasso')

        // When a new annotation drawing starts, mark as drawing and clear old annotations
        annotationLayerRef.current.geoOn(geo.event.annotation.add, (e: any) => {
            isDrawingRef.current = true
            justCompletedRef.current = false
            const newAnnotation = e.annotation
            const existingAnnotations = annotationLayerRef.current.annotations()
            for (const ann of existingAnnotations) {
                if (ann !== newAnnotation) {
                    annotationLayerRef.current.removeAnnotation(ann)
                }
            }
        })

        // Register annotation completion event listener
        annotationLayerRef.current.geoOn(geo.event.annotation.state, handleNewAnnotation)

        // Use GeoJS mouseclick to clear polygon; skip the click that ends a lasso
        map.geoOn(geo.event.mouseclick, () => {
            if (isDrawingRef.current) return
            if (justCompletedRef.current) {
                justCompletedRef.current = false
                return
            }
            clearLassoPolygon()
        })

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
            if (e.key === 'Control' || e.key === 'Meta') {
                isCtrlHeldRef.current = true
                setIsCtrlHeld(true)
            }
        }
        const handleKeyUp = (e: KeyboardEvent) => {
            if (e.key === 'Control' || e.key === 'Meta') {
                isCtrlHeldRef.current = false
                setIsCtrlHeld(false)
            }
        }

        document.addEventListener('keydown', handleKeyDown)
        document.addEventListener('keyup', handleKeyUp)

        return () => {
            map.exit()
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
            setAnnotationMode('polygon')
        } else {
            setAnnotationMode('lasso')
        }
    }, [isCtrlHeld])

    return <div ref={mapDivRef} style={{ width: '100%', height: '100%' }} />
}
