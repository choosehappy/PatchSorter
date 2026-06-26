import { useState } from 'react'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, OnSelectedRowsChangedEventArgs } from 'slickgrid-react'
import type { LabelClassResponse } from '../../api_client'

interface LabelClassesTableProps {
    projectId: number
    labelClasses: LabelClassResponse[]
    isLoading: boolean
    onMutated: () => void
}

export default function LabelClassesTable({ labelClasses, isLoading }: LabelClassesTableProps) {
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

    const colorFormatter = (_row: number, _cell: number, value: unknown) =>
        `<span style="display:inline-block;width:20px;height:20px;border-radius:3px;background:${value};border:1px solid #ccc;vertical-align:middle"></span> ${value}`

    const columns: Column[] = [
        { id: 'id',      name: 'Id',      field: 'id',         sortable: true },
        { id: 'name',    name: 'Name',    field: 'name',       sortable: true },
        { id: 'color',   name: 'Color',   field: 'color_code', sortable: false, formatter: colorFormatter },
        { id: 'created', name: 'Created', field: 'event_ts',   sortable: true,
          formatter: (_r: number, _c: number, v: unknown) => v ? new Date(v as string).toLocaleDateString() : '' },
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
        setSelectedIds(new Set(rows))
    }

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
            <div id="label-classes-container" style={{ height }}>
                <SlickgridReact
                    gridId="label-classes-grid"
                    columns={columns}
                    options={gridOptions}
                    dataset={isLoading ? [] : dataset}
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
