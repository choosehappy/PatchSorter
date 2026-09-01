import { useRef, useEffect } from 'react'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, OnSelectedRowsChangedEventArgs } from 'slickgrid-react'
import type { LabelClassResponse } from '../../api_client'

interface LabelClassesTableProps {
    projectId: number
    labelClasses: LabelClassResponse[]
    isLoading: boolean
    onMutated: () => void
    selectedIds: Set<number>
    onSelectionChange: (ids: Set<number>) => void
    onEdit: (labelClass: LabelClassResponse) => void
}

export default function LabelClassesTable({ labelClasses, isLoading, selectedIds, onSelectionChange, onEdit }: LabelClassesTableProps) {
    const gridRef = useRef<any>(null)
    const labelClassesRef = useRef(labelClasses)
    labelClassesRef.current = labelClasses

    const colorFormatter = (_row: number, _cell: number, value: unknown) =>
        `<span style="display:inline-block;width:20px;height:20px;border-radius:3px;background:${value};border:1px solid #ccc;vertical-align:middle"></span> ${value}`

    const columns: Column[] = [
        { id: 'id',      name: 'Id',      field: 'id',         sortable: true },
        { id: 'name',    name: 'Name',    field: 'name',       sortable: true },
        { id: 'color',   name: 'Color',   field: 'color_code', sortable: false, formatter: colorFormatter },
        { id: 'created', name: 'Created', field: 'event_ts',   sortable: true,
          formatter: (_r: number, _c: number, v: unknown) => v ? new Date(v as string).toLocaleDateString() : '' },
        {
            id: 'actions',
            name: 'Actions',
            field: 'id',
            sortable: false,
            formatter: (row: number) => {
                const lc = labelClassesRef.current[row]
                if (!lc) return ''
                return `<button class="btn btn-sm btn-outline-primary" data-lcid="${lc.label_class_id}">Edit</button>`
            },
        },
    ]

    const gridOptions: GridOption = {
        enableAutoResize: true,
        enableCheckboxSelector: true,
        enableSelection: true,
        checkboxSelector: { hideInFilterHeaderRow: false },
        rowHeight: 40,
        forceFitColumns: true,
        autoResize: { container: '#label-classes-container' },
    }

    const handleSelectedRowsChanged = (e: CustomEvent<{ eventData: unknown; args: OnSelectedRowsChangedEventArgs }>) => {
        const rows = e.detail.args.rows ?? []
        if (gridRef.current) {
            const ids = new Set(rows.map(r => (gridRef.current!.slickGrid.getDataItem(r) as { id: number }).id))
            onSelectionChange(ids)
        }
    }

    useEffect(() => {
        if (selectedIds.size === 0 && gridRef.current) {
            gridRef.current.slickGrid.setSelectedRows([])
        }
    }, [selectedIds.size])

    useEffect(() => {
        const handler = (event: Event) => {
            const target = event.target as HTMLButtonElement
            if (target.tagName === 'BUTTON' && target.dataset.lcid) {
                const id = parseInt(target.dataset.lcid, 10)
                const lc = labelClassesRef.current.find(l => l.label_class_id === id)
                if (lc) {
                    onEdit(lc)
                }
            }
        }
        document.addEventListener('click', handler)
        return () => document.removeEventListener('click', handler)
    }, [onEdit])

    useEffect(() => {
        if (!gridRef.current) return
        const dataView = gridRef.current.dataView
        if (dataView) {
            // setItems with the id field name re-syncs the whole dataset
            // and slickgrid will diff+redraw rows whose data actually changed
            dataView.setItems(dataset, 'id')
            gridRef.current.slickGrid.invalidate()
            gridRef.current.slickGrid.render()
        }
    }, [labelClasses])

    const dataset = labelClasses.map(lc => ({
        id: lc.label_class_id,
        name: lc.name,
        color_code: lc.color_code ?? '',
        event_ts: lc.event_ts,
    }))

    const height = Math.max(150, labelClasses.length * 40 + 60)

    return (
        <section>
            <h5>Label Classes</h5>
            <div id="label-classes-container" style={{ height, overflow: 'hidden' }}>
                <SlickgridReact
                    gridId="label-classes-grid"
                    columns={columns}
                    options={gridOptions}
                    dataset={isLoading ? [] : dataset}
                    onReactGridCreated={e => { gridRef.current = e.detail }}
                    onSelectedRowsChanged={handleSelectedRowsChanged}
                />
            </div>
            {selectedIds.size > 0 && (
                <small className="text-muted mt-1 d-block">
                    {selectedIds.size} label class{selectedIds.size > 1 ? 'es' : ''} selected
                </small>
            )}
        </section>
    )
}
