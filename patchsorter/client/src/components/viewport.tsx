import { useEffect, useRef } from 'react'
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
    polygonTool: boolean
    onPolygonComplete: (bbox: { x_min: number; x_max: number; y_min: number; y_max: number }) => void
    onClear: () => void
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
    polygonTool,
    onPolygonComplete,
    onClear,
}: ViewportProps) {
    const osmZoomOffset = worldInfo?.osm_zoom_offset ?? 8
    const maxOsmZoom = (worldInfo?.max_level ?? 12) - osmZoomOffset
    const mapDivRef = useRef<HTMLDivElement>(null)
    const mapRef = useRef<any>(null)
    const overlayLayerRef = useRef<any>(null)
    const paramsRef = useRef<any>(null)
    const annotationLayerRef = useRef<any>(null)
    const polygonFeatureRef = useRef<any>(null)
    const annotationLayerCreatedRef = useRef(false)

    function getPolygonFromAnnotationLayer(): number[][][] | null {
        if (!annotationLayerRef.current) return null
        const annotations = annotationLayerRef.current.annotations()
        if (annotations && annotations.length > 0) {
            const geometry = annotations[0].geojson()?.geometry
            if (geometry?.type === 'Polygon') {
                return geometry.coordinates
            }
        }
        return null
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
        overlayLayerRef.current = mapRef.current.createLayer('osm', paramsRef.current.layer)
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
        overlayLayerRef.current = map.createLayer('osm', params.layer)

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

        return () => {
            map.exit()
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

    // Polygon annotation layer: enable/disable based on polygonTool prop
    useEffect(() => {
        const map = mapRef.current
        if (!map) return

        if (polygonTool) {
            // Create annotation layer if not already created
            if (!annotationLayerCreatedRef.current) {
                annotationLayerRef.current = map.createLayer('annotation')
                annotationLayerCreatedRef.current = true
            }

            // Set polygon mode on the annotation layer
            const annotationLayer = annotationLayerRef.current
            annotationLayer.mode('polygon', undefined, {
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

            // Listen for polygon completion via annotation state event
            const handleNewAnnotation = () => {
                // Get polygon coordinates from annotation layer
                const coordinates = getPolygonFromAnnotationLayer()
                if (!coordinates || coordinates.length === 0) return

                // Compute world-space bbox from polygon coordinates
                const ring = coordinates[0]
                let wxMin = Infinity, wxMax = -Infinity, wyMin = Infinity, wyMax = -Infinity
                for (const [x, y] of ring) {
                    if (x < wxMin) wxMin = x
                    if (x > wxMax) wxMax = x
                    if (y < wyMin) wyMin = y
                    if (y > wyMax) wyMax = y
                }

                if (wxMin < wxMax && wyMin < wyMax) {
                    onPolygonComplete({ x_min: wxMin, x_max: wxMax, y_min: wyMin, y_max: wyMax })
                }

                // Disable polygon mode after completing a polygon
                annotationLayer.mode('none')

                // Clear annotations so layer can be reused
                annotationLayer.removeAllAnnotations()
            }

            annotationLayer.geoOn(geo.event.annotation.state, handleNewAnnotation)

            // Store the handler reference for cleanup
            polygonFeatureRef.current = { handler: handleNewAnnotation }

        } else {
            // Disable polygon mode and clean up annotation layer
            if (annotationLayerRef.current) {
                annotationLayerRef.current.mode('none')
                annotationLayerRef.current.geoOff(geo.event.annotation.state, polygonFeatureRef.current?.handler)
                map.deleteLayer(annotationLayerRef.current)
                annotationLayerRef.current = null
                annotationLayerCreatedRef.current = false
            }
            polygonFeatureRef.current = null
        }

        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [polygonTool])

    // Click on map clears annotation layer and gallery items
    function handleMapClick() {
        const map = mapRef.current
        if (!map) return

        if (annotationLayerRef.current) {
            annotationLayerRef.current.mode('none')
            annotationLayerRef.current.removeAllAnnotations()
        }

        onClear()
    }

    useEffect(() => {
        const map = mapRef.current
        if (!map) return

        function onMapClick() {
            handleMapClick()
        }

        if (typeof geo !== 'undefined' && geo.event?.pan) {
            map.geoOn(geo.event.pan, onMapClick)
        }

        return () => {
            if (typeof geo !== 'undefined' && geo.event?.pan) {
                map.geoOff(geo.event.pan, onMapClick)
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return <div ref={mapDivRef} style={{ width: '100%', height: '100%' }} />
}
