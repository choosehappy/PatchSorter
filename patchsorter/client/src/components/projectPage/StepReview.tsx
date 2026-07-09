import { useMemo, useRef, useCallback, useEffect } from 'react'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, SlickgridReactInstance } from 'slickgrid-react'
import type { ReviewRow, Approach } from './useUpload'

interface StepReviewProps {
    approach: Approach | null
    reviewData: ReviewRow[] | null
    isLoading: boolean
}

export default function StepReview({ reviewData, isLoading, approach: _approach }: StepReviewProps) {
    const gridRef = useRef<SlickgridReactInstance | null>(null)

    const errorCount = useMemo(() => reviewData?.filter(r => r.status === 'error').length ?? 0, [reviewData])

    const buildColumns = useCallback((): Column[] => {
        const truncateStyle = 'text-truncate'
        const maxWidth = 220

        const statusFormatter = (_row: number, _cell: number, value: unknown) => {
            const s = String(value ?? '')
            const bg = s === 'ok' ? 'success' : 'danger'
            return `<span class="badge bg-${bg}">${s}</span>`
        }

        const errorFormatter = (_row: number, _cell: number, value: unknown) => {
            const e = String(value ?? '')
            if (!e) return ''
            return `<span class="text-danger" style="font-size:0.78rem" title="${e}">${e}</span>`
        }

        const pathFormatter = (_field: string) => (_row: number, _cell: number, value: unknown) => {
            const v = String(value ?? '')
            if (!v) return '<span class="text-muted">—</span>'
            return `<span class="${truncateStyle}" style="max-width:${maxWidth}px" title="${v}">${v}</span>`
        }

        return [
            { id: 'image',   name: 'Image',       field: 'image',   sortable: true,  formatter: pathFormatter('image') },
            { id: 'mask',    name: 'Mask',         field: 'mask',    sortable: true,  formatter: pathFormatter('mask') },
            { id: 'csv',     name: 'Label',        field: 'csv',     sortable: true,  formatter: pathFormatter('csv') },
            { id: 'error',   name: 'Error',        field: 'error',   sortable: false, formatter: errorFormatter },
            { id: 'status',  name: 'Status',       field: 'status',  sortable: true,  formatter: statusFormatter },
        ]
    }, [])

    const dataset = useMemo(() =>
        (reviewData ?? []).map((row, i) => ({
            id: i,
            image: row.image,
            mask: row.mask,
            csv: row.csv,
            error: row.error,
            status: row.status,
        })),
        [reviewData],
    )

    const gridOptions: GridOption = {
        enableAutoResize: true,
        enableSelection: true,
        rowHeight: 32,
        forceFitColumns: true,
        autoResize: { container: '#upload-review-container' },
        ...({ headerRowOptions: { filterPlugin: { filterCollectionMetadataItem: { placeholder: 'Search' } } } } as GridOption),
    }

    const onGridReady = useCallback((reactGrid: SlickgridReactInstance) => {
        gridRef.current = reactGrid
    }, [])

    useEffect(() => {
        if (gridRef.current) {
            gridRef.current.slickGrid.invalidate()
        }
    }, [dataset])

    const height = Math.max(200, (reviewData?.length ?? 0) * 32 + 44)

    if (isLoading || reviewData === null) {
        return (
            <div className="d-flex align-items-center gap-2 py-4">
                {isLoading ? (
                    <>
                        <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
                        <span>Validating paths…</span>
                    </>
                ) : (
                    <span className="text-danger">Validation failed. Please go back and check your input.</span>
                )}
            </div>
        )
    }

    return (
        <div>
            {errorCount > 0 && (
                <div className="alert alert-warning py-2 mb-2" style={{ fontSize: '0.875rem' }}>
                    {errorCount} row{errorCount !== 1 ? 's have' : ' has'} errors. Consider fixing the issues before processing.
                </div>
            )}
            {reviewData.length === 0 && (
                <p className="text-muted text-center py-3">No rows returned from validation.</p>
            )}
            {reviewData.length > 0 && (
                <div id="upload-review-container" style={{ height }}>
                    <SlickgridReact
                        gridId="upload-review-grid"
                        columns={buildColumns()}
                        options={gridOptions}
                        dataset={dataset}
                        onReactGridCreated={e => onGridReady(e.detail)}
                    />
                </div>
            )}
        </div>
    )
}
