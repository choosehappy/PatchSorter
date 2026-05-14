import { useEffect, useRef } from 'react'

// GeoJS loaded via CDN in index.html
declare const geo: any

const TILE_SERVER = ''         // relative URL — same origin as the page
const OSM_ZOOM_OFFSET = 8
const MAX_LEVEL = 12
const MAX_OSM_ZOOM = MAX_LEVEL - OSM_ZOOM_OFFSET   // 4
const WORLD_SIZE = 4096

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
    onBoundsChange: (bounds: MapBounds) => void
    onZoomChange: (osmZoom: number, level: number) => void
}

export default function Viewport({
    colorBy,
    filterBy,
    selectedCells,
    numClasses,
    onBoundsChange,
    onZoomChange,
}: ViewportProps) {
    const mapDivRef = useRef<HTMLDivElement>(null)
    const mapRef = useRef<any>(null)
    const overlayLayerRef = useRef<any>(null)
    const paramsRef = useRef<any>(null)

    // Keep a mutable ref for tile-URL state so the GeoJS callback always reads
    // the latest values without needing to re-register it.
    const tileStateRef = useRef({ colorBy, filterBy, selectedCells, numClasses })
    tileStateRef.current = { colorBy, filterBy, selectedCells, numClasses }

    function buildTileUrl(x: number, y: number, z: number): string {
        const { colorBy, filterBy, selectedCells, numClasses } = tileStateRef.current
        const sumOver = colorBy !== 'gt' ? 'gt' : 'pred'
        let url = `${TILE_SERVER}/tiles/${z}/${x}/${y}.png?sum_over=${sumOver}`

        const bounds = mapRef.current.bounds()
        url += `&vp_x_min=${bounds.left}&vp_y_min=${bounds.top}`
            + `&vp_x_max=${bounds.right}&vp_y_max=${bounds.bottom}`

        if (filterBy !== 'all' || selectedCells.size < numClasses * numClasses) {
            const pairs = Array.from(selectedCells)
            if (pairs.length > 0 && pairs.length < numClasses * numClasses) {
                pairs.forEach(pair => { url += `&lp=${pair}` })
            }
        }
        return url
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
        params.map.max = MAX_OSM_ZOOM
        params.map.center = { x: WORLD_SIZE / 2, y: WORLD_SIZE / 2 }
        paramsRef.current = params

        const map = geo.map(params.map)
        mapRef.current = map

        params.layer.url = (x: number, y: number, z: number) => buildTileUrl(x, y, z)
        params.layer.nearestPixel = true
        params.layer.maxLevel = MAX_OSM_ZOOM
        overlayLayerRef.current = map.createLayer('osm', params.layer)

        // Zoom info callback
        map.geoOn(geo.event.zoom, () => {
            const z = Math.round(map.zoom())
            onZoomChange(z, z + OSM_ZOOM_OFFSET)
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

        // Auto-refresh tile cache every 5 s
        const interval = setInterval(() => {
            if (!overlayLayerRef.current) return
            overlayLayerRef.current.reset()
            const m = overlayLayerRef.current.map()
            const b = m.bounds(undefined, null)
            const zoom = overlayLayerRef.current._options.tileRounding(m.zoom())
            overlayLayerRef.current._getTiles(zoom, b, true, false)
            m.draw()
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
