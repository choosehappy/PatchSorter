import { useRef, useCallback, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, SlickgridReactInstance, OnSelectedRowsChangedEventArgs } from 'slickgrid-react'
import type { ImageResponse, ImageStatsResponse, LabelClassResponse, GetImageThumbnailProjectsProjectIdImagesImageIdThumbnailGetData } from '../../api_client'
import {getImageStatsProjectsProjectIdImagesImageIdStatsGet } from '../../api_client'
import { client } from '../../api_client/client.gen'
interface ImagesTableProps {
    projectId: number
    images: ImageResponse[]
    labelClasses: LabelClassResponse[]
    isLoading: boolean
    onMutated: () => void
    selectedIds: Set<number>
    onSelectionChange: (ids: Set<number>) => void
}

export default function ImagesTable({ projectId, images, labelClasses, isLoading, selectedIds, onSelectionChange }: ImagesTableProps) {
    const navigate = useNavigate()
    const gridRef = useRef<SlickgridReactInstance | null>(null)

    const imageStatQueries = useQueries({
        queries: images.map(img => ({
            queryKey: ['imageStats', projectId, img.image_id],
            queryFn: () => getImageStatsProjectsProjectIdImagesImageIdStatsGet({
                path: { project_id: projectId, image_id: img.image_id }
            }).then(r => r.data),
            enabled: images.length > 0,
            staleTime: 30_000,
        }))
    })

    const statsByImageId: Record<number, ImageStatsResponse | null> = useMemo(() =>
        Object.fromEntries(images.map((img, i) => [
            img.image_id,
            imageStatQueries[i]?.isSuccess ? (imageStatQueries[i].data as ImageStatsResponse) : null
        ])), [images, imageStatQueries])

    function buildThumbnailURL(imageId: number): string {
        const options = {
            path: { project_id: projectId, image_id: imageId },
            url: '/projects/{project_id}/images/{image_id}/thumbnail/' satisfies GetImageThumbnailProjectsProjectIdImagesImageIdThumbnailGetData['url'],
        } as GetImageThumbnailProjectsProjectIdImagesImageIdThumbnailGetData

        return client.buildUrl(options)
    }

    const buildColumns = useCallback((): Column[] => {
        const thumbnailFormatter = (_row: number, _cell: number, value: unknown) => {
            const src = buildThumbnailURL(value as number)
            return (
                '<span class="spinner-border spinner-border-sm" role="status"></span>' +
                '<span class="text-danger" style="display:none;font-size:1.5rem">&times;</span>' +
                `<img src="${src}" height="56" style="display:none"` +
                ` onload="this.previousElementSibling.previousElementSibling.style.display='none';this.style.display='block'"` +
                ` onerror="this.previousElementSibling.previousElementSibling.style.display='none';this.previousElementSibling.style.display='inline'">`
            )
        }

        const spinnerOrValue = (_row: number, _cell: number, value: unknown) =>
            value === null
                ? '<span class="spinner-border spinner-border-sm" role="status"></span>'
                : String(value ?? '')

        const actionsFormatter = (_row: number, _cell: number, _value: unknown, _col: Column, dataContext: { id: number }) => {
            const btn = document.createElement('button')
            btn.className = 'btn btn-primary btn-sm'
            btn.textContent = 'Open Image Viewer'
            btn.disabled = true
            return btn
        }

        return [
            { id: 'thumbnail', name: '',              field: 'image_id',        sortable: false, formatter: thumbnailFormatter },
            { id: 'id',        name: 'ID',            field: 'id',              sortable: true },
            { id: 'name',      name: 'Name',          field: 'name',            sortable: true },
            { id: 'width',     name: 'Width',         field: 'width',           sortable: true },
            { id: 'height',    name: 'Height',        field: 'height',          sortable: true },
            { id: 'total',     name: 'Total Patches', field: 'total_patches',   sortable: true, formatter: spinnerOrValue },
            { id: 'labeled',   name: 'Labeled',       field: 'labeled_patches', sortable: true, formatter: spinnerOrValue },
            { id: 'actions',   name: '',              field: 'image_id',        sortable: false, formatter: actionsFormatter },
        ]
    }, [labelClasses, projectId, navigate])

    useEffect(() => {
        if (gridRef.current) {
            gridRef.current.slickGrid.invalidate()
        }
    }, [statsByImageId])

    const dataset = useMemo(() => images.map(img => {
        const s = statsByImageId[img.image_id]
        return {
            id: img.image_id,
            image_id: img.image_id,
            name: img.name,
            width: img.base_width,
            height: img.base_height,
            total_patches: s?.total_patches ?? null,
            labeled_patches: s?.labeled_patches ?? null,
        }
    }), [images, statsByImageId])

    const gridOptions: GridOption = {
        enableAutoResize: true,
        enableCheckboxSelector: true,
        enableSelection: true,
        checkboxSelector: { hideInFilterHeaderRow: false },
        rowHeight: 64,
        forceFitColumns: true,
        autoResize: { container: '#images-container',
            maxHeight: 800,
            minHeight: 200,
         },
    }

    const onGridReady = useCallback((reactGrid: SlickgridReactInstance) => {
        gridRef.current = reactGrid
    }, [])

    useEffect(() => {
        if (selectedIds.size === 0 && gridRef.current) {
            gridRef.current.slickGrid.setSelectedRows([])
        }
    }, [selectedIds.size])

    const handleSelectedRowsChanged = useCallback((e: CustomEvent<{ eventData: unknown; args: OnSelectedRowsChangedEventArgs }>) => {
        const rows = e.detail.args.rows ?? []
        if (gridRef.current) {
            const ids = new Set(rows.map(r => (gridRef.current!.slickGrid.getDataItem(r) as { id: number }).id))
            onSelectionChange(ids)
        }
    }, [onSelectionChange])

    const height = Math.max(200, images.length * 64 + 60)

    return (
        <section>
            <h5>Images</h5>
            <div id="images-container" style={{ height, overflow: 'hidden'}}>
                <SlickgridReact
                    gridId="images-grid"
                    columns={buildColumns()}
                    options={gridOptions}
                    dataset={isLoading ? [] : dataset}
                    onReactGridCreated={e => onGridReady(e.detail)}
                    onSelectedRowsChanged={handleSelectedRowsChanged}
                />
            </div>
            {selectedIds.size > 0 && (
                <small className="text-muted mt-1 d-block">
                    {selectedIds.size} image{selectedIds.size > 1 ? 's' : ''} selected
                </small>
            )}
        </section>
    )
}
