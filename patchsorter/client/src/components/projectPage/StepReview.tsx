import { useMemo, useRef, useCallback, useEffect } from 'react'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, SlickgridReactInstance } from 'slickgrid-react'
import type { ReviewRow, Approach } from './useUpload'
import { Editors } from 'slickgrid-react'
import { MAGNIFICATION_OPTIONS } from '../../constants'

interface StepReviewProps {
    approach: Approach | null
    reviewData: ReviewRow[] | null
    isLoading: boolean
    onRowChange: (index: number, updates: Partial<ReviewRow>) => void
}

export default function StepReview({ reviewData, isLoading, approach: _approach, onRowChange }: StepReviewProps) {
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

        const baseMagFormatter = (_row: number, _cell: number, value: unknown) => {
            const v = Number(value ?? 0)
            return v ? String(v) : '<span class="text-muted">—</span>'
        }

        return [
            { id: 'image',   name: 'Image',       field: 'image',   sortable: true,  formatter: pathFormatter('image') },
            { id: 'mask',    name: 'Mask',         field: 'mask',    sortable: true,  formatter: pathFormatter('mask') },
            { id: 'csv',     name: 'Label',        field: 'csv',     sortable: true,  formatter: pathFormatter('csv') },
            {
                id: 'base_mag',
                name: 'Base Mag',
                field: 'base_mag',
                sortable: true,
                editor: {
                    model: Editors.singleSelect,
                    collection: [
                        { value: '', label: '—' },
                        ...MAGNIFICATION_OPTIONS.map(m => ({ value: m, label: String(m) })),
                    ],
                    massUpdate: true,
                    options: { showClear: true },
                },
                formatter: baseMagFormatter,
            },
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
            base_mag: row.base_mag ?? '',
        })),
        [reviewData],
    )

    const gridOptions: GridOption = {
        enableAutoResize: true,
        enableSelection: true,
        rowHeight: 32,
        forceFitColumns: true,
        autoResize: { container: '#upload-review-container' },
        editable: true,
        autoEdit: true,
        autoCommitEdit: true,
        enableCellNavigation: true,
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
                        onCellChange={e => {
                            const dataContext = e.detail.args?.item
                            const id = dataContext.id
                            const val = dataContext?.base_mag
                            onRowChange(id, { base_mag: val != null && val !== '' ? Number(val) : null })
                        }}
                    />
                </div>
            )}
        </div>
    )
}
