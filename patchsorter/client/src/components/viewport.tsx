import { useEffect, useRef } from 'react'
import { client } from '../api_client/client.gen'
import { type ServeTileAggTilesZxyPngGetData, type WorldInfo } from '../api_client'

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
    colorBy: string
    filterBy: string
    selectedCells: Set<string>
    numClasses: number
    worldInfo: WorldInfo | null
    onBoundsChange: (bounds: MapBounds) => void
    onZoomChange: (osmZoom: number, level: number) => void
}

export default function Viewport({
    colorBy,
    filterBy,
    selectedCells,
    numClasses,
    worldInfo,
    onBoundsChange,
    onZoomChange,
}: ViewportProps) {
    const osmZoomOffset = worldInfo?.osm_zoom_offset ?? 8
    const maxOsmZoom = (worldInfo?.max_level ?? 12) - osmZoomOffset
    const mapDivRef = useRef<HTMLDivElement>(null)
    const mapRef = useRef<any>(null)
    const overlayLayerRef = useRef<any>(null)
    const paramsRef = useRef<any>(null)

    // Keep a mutable ref for tile-URL state so the GeoJS callback always reads
    // the latest values without needing to re-register it.
    const tileStateRef = useRef({ colorBy, filterBy, selectedCells, numClasses })
    tileStateRef.current = { colorBy, filterBy, selectedCells, numClasses }

    const cacheKeyRef = useRef(Date.now())

    function buildTileUrl(x: number, y: number, z: number): string {
        const { colorBy, filterBy, selectedCells, numClasses } = tileStateRef.current
        const sumOver = colorBy !== 'gt' ? 'gt' : 'pred'
        const bounds = mapRef.current.bounds()

        // TypeScript will complain if this is no longer true due to changes in the API.
        const tile_url = '/agg/tiles/{z}/{x}/{y}.png' satisfies ServeTileAggTilesZxyPngGetData['url']

        // Build query object without undefined properties
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
            path: { z, x, y },
            query,
            url: tile_url
        } as ServeTileAggTilesZxyPngGetData

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

        params.layer.url = (x: number, y: number, z: number) => buildTileUrl(x, y, z)
        params.layer.nearestPixel = true
        params.layer.maxLevel = maxOsmZoom
        overlayLayerRef.current = map.createLayer('osm', params.layer)

        // Zoom info callback
        map.geoOn(geo.event.zoom, () => {
            const z = Math.round(map.zoom())
            onZoomChange(z, z + osmZoomOffset)
        })
        map.geoTrigger(geo.event.zoom)

        // Pan / zoom idle → notify parent to re-fetch confusion matrix
        let idleTimeout: ReturnType<typeof setTimeout> | null = null
        function onMapIdle() {
            if (idleTimeout) clearTimeout(idleTimeout)
            idleTimeout = setTimeout(() => {
                onBoundsChange(map.bounds())
            }, 200)
        }
        map.geoOn(geo.event.pan, onMapIdle)
        map.geoOn(geo.event.zoom, onMapIdle)

        // Auto-refresh tile cache every 5 s via URL invalidation.
        // Update the URL function in-place (new timestamp → bypasses browser cache)
        // then reset the tile cache, avoiding the flash of a full layer rebuild.
        const interval = setInterval(() => {
            if (!overlayLayerRef.current) return
            cacheKeyRef.current = Date.now()
            overlayLayerRef.current.url((x: number, y: number, z: number) => buildTileUrl(x, y, z))
            overlayLayerRef.current.reset()
            overlayLayerRef.current.map().draw()
        }, 5000)

        return () => {
            clearInterval(interval)
            map.exit()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // Rebuild layer (force tile cache invalidation) when filter/colour state changes
    useEffect(() => {
        if (mapRef.current) rebuildLayer()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [colorBy, filterBy, selectedCells])

    return <div ref={mapDivRef} style={{ width: '100%', height: '100%' }} />
}
