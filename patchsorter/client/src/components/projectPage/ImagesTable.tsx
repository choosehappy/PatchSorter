import { useRef, useState, useCallback, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueries } from '@tanstack/react-query'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, SlickgridReactInstance, OnSelectedRowsChangedEventArgs } from 'slickgrid-react'
import type { ImageResponse, ImageStatsResponse, LabelClassResponse } from '../../api_client'
import { getImageStatsProjectsProjectIdImagesImageIdStatsGet } from '../../api_client'

interface ImagesTableProps {
    projectId: number
    images: ImageResponse[]
    labelClasses: LabelClassResponse[]
    isLoading: boolean
    onMutated: () => void
}

export default function ImagesTable({ projectId, images, labelClasses, isLoading }: ImagesTableProps) {
    const navigate = useNavigate()
    const gridRef = useRef<SlickgridReactInstance | null>(null)
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

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

    const buildColumns = useCallback((): Column[] => {
        const thumbnailFormatter = (_row: number, _cell: number, value: unknown) => {
            const src = `/projects/${projectId}/images/${value}/thumbnail/`
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
            btn.textContent = 'Open Labeler'
            btn.addEventListener('click', (e) => {
                e.stopPropagation()
                navigate(`/project/${projectId}/labeler?image=${dataContext.id}`)
            })
            return btn
        }

        return [
            { id: 'thumbnail', name: '',              field: 'image_id',        sortable: false, formatter: thumbnailFormatter },
            { id: 'name',      name: 'Name',          field: 'name',            sortable: true },
            { id: 'width',     name: 'Width',         field: 'width',           sortable: true },
            { id: 'height',    name: 'Height',        field: 'height',          sortable: true },
            { id: 'total',     name: 'Total Patches', field: 'total_patches',   sortable: true, formatter: spinnerOrValue },
            { id: 'labeled',   name: 'Labeled',       field: 'labeled_patches', sortable: true, formatter: spinnerOrValue },
            { id: 'actions',   name: '',              field: 'image_id',        sortable: false, formatter: actionsFormatter },
        ]
    }, [labelClasses, projectId, navigate])

    useEffect(() => {
        if (!gridRef.current) return
        const cols = buildColumns()
        gridRef.current.slickGrid.setColumns(cols)
    }, [labelClasses, selectedIds.size, buildColumns])

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
        autoResize: { container: '#images-container' },
    }

    const onGridReady = useCallback((reactGrid: SlickgridReactInstance) => {
        gridRef.current = reactGrid
    }, [])

    const handleSelectedRowsChanged = useCallback((e: CustomEvent<{ eventData: unknown; args: OnSelectedRowsChangedEventArgs }>) => {
        const rows = e.detail.args.rows ?? []
        if (gridRef.current) {
            const ids = new Set(rows.map(r => (gridRef.current!.slickGrid.getDataItem(r) as { id: number }).id))
            setSelectedIds(ids)
        }
    }, [])

    const height = Math.max(200, images.length * 64 + 60)

    return (
        <section>
            <h5>Images</h5>
            <div id="images-container" style={{ height }}>
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
