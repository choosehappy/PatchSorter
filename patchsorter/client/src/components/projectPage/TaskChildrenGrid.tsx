import * as React from 'react'
import { SlickgridReact } from 'slickgrid-react'
import type { GridOption, SlickgridReactInstance, Column } from 'slickgrid-react'
import { SlickCustomTooltip } from '@slickgrid-universal/custom-tooltip-plugin'
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css'
import { searchRayTasks } from '../../api_client'
import Button from 'react-bootstrap/Button'
import Collapse from 'react-bootstrap/Collapse'
import Spinner from 'react-bootstrap/Spinner'
import './taskChildrenGrid.css'

interface RayTaskState {
    task_id: string
    name: string
    func_or_class_name: string
    state: string
    creation_time?: number | null
    end_time?: number | null
    error_message?: string | null
}

interface TaskRow {
    id: string
    task_id: string
    name: string
    func_or_class_name: string
    state: string
    error_message: string | null
    creation_time_ms: number | null
    end_time_ms: number | null
    actor_progress: number
}

const POLL_INTERVAL_MS = 3000

const STATE_COLORS: Record<string, string> = {
    PENDING: '#6c757d',
    RUNNING: '#0d6efd',
    DONE: '#198754',
    FAILED: '#dc3545',
    CANCELLED: '#6f42c1',
}

interface TaskChildrenGridProps {
    parentTaskId: string
    containerId?: string
    onCompletion?: () => void
}

export default function TaskChildrenGrid({ parentTaskId, containerId, onCompletion }: TaskChildrenGridProps) {
    const pollRef = React.useRef<number | null>(null)
    const doneRef = React.useRef(false)
    const fetchChildrenOnceRef = React.useRef<(() => Promise<void>) | null>(null)

    const [columnDefinitions, setColumnDefinitions] = React.useState<Column[]>([])
    const [gridOptions, setGridOptions] = React.useState<GridOption | undefined>()
    const [dataset, setDataset] = React.useState<TaskRow[]>([])
    const [reactGrid, setReactGrid] = React.useState<SlickgridReactInstance | undefined>()
    const [isExpanded, setIsExpanded] = React.useState(false)
    const [loading, setLoading] = React.useState(true)
    const [error, setError] = React.useState<string | null>(null)

    const startPolling = React.useCallback(() => {
        doneRef.current = false
        if (pollRef.current) {
            clearInterval(pollRef.current)
        }
        fetchChildrenOnceRef.current?.()
        pollRef.current = window.setInterval(() => {
            if (!doneRef.current) {
                fetchChildrenOnceRef.current?.()
            }
        }, POLL_INTERVAL_MS)
    }, [])

    const stopPolling = React.useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current)
            pollRef.current = null
        }
    }, [])

    const defineGrid = () => {
        const stateFormatter = (_row: number, _cell: number, value: string, _columnDef: Column, dataContext: TaskRow) => {
            const s = (value ?? '').toString().toUpperCase()
            const bgColor = STATE_COLORS[s] || '#6c757d'
            const textColor = s === 'RUNNING' ? '#fff' : undefined
            const errorMsg = (dataContext?.error_message ?? '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            return errorMsg
                ? `<span title="${errorMsg}" style="background-color: ${bgColor}; color: ${textColor || 'inherit'}; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem;">${s}</span>`
                : `<span style="background-color: ${bgColor}; color: ${textColor || 'inherit'}; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem;">${s}</span>`
        }

        const columns: Column[] = [
            {
                id: 'func',
                name: 'Task Name',
                field: 'name',
                sortable: true,
                minWidth: 120,
                customTooltip: {
                    useRegularTooltip: false,
                },
            },
            {
                id: 'state',
                name: 'State',
                field: 'state',
                sortable: true,
                minWidth: 60,
                formatter: stateFormatter,
                customTooltip: {
                    useRegularTooltip: false,
                },
            },
        ]

        const options: GridOption = {
            enableAutoResize: false,
            forceFitColumns: true,
            autoResize: {
                container: `#${containerId}`,
                maxHeight: 200,
                minWidth: 300,
            },
            enableCellNavigation: true,
            enableSelection: true,
            showColumnHeader: false,
            externalResources: [new SlickCustomTooltip() as any],
        }

        setColumnDefinitions(columns)
        setGridOptions(options)
    }

    const reactGridReady = React.useCallback((reactGrid: SlickgridReactInstance) => {
        setReactGrid(reactGrid)
    }, [])

    const fetchChildrenOnce = React.useCallback(async () => {
        fetchChildrenOnceRef.current = fetchChildrenOnce
        try {
            const res = await searchRayTasks({
                body: [['parent_task_id', '=', parentTaskId]],
            })
            if (res.error) {
                const status = (res.error as any)?.status
                if (status !== 404) {
                    setError(`Ray task query failed: ${(res.error as any)?.statusText || 'Unknown error'}`)
                }
                setDataset([])
                setLoading(false)
                return
            }
            const result = res.data! as unknown as RayTaskState[]
            const rows: TaskRow[] = result.map((t, index) => ({
                id: String(index),
                task_id: t.task_id,
                name: t.name,
                func_or_class_name: t.func_or_class_name,
                state: t.state,
                error_message: t.error_message ?? null,
                creation_time_ms: t.creation_time ?? null,
                end_time_ms: t.end_time ?? null,
                actor_progress: 0,
            }))

            reactGrid?.gridService.resetGrid()
            setDataset(rows)
            setLoading(false)
            setError(null)

            if (result.length === 0) return

            const allDone = result.every((t) => t.state === 'DONE')
            const anyFailed = result.some((t) => t.state === 'FAILED')

            if (allDone || anyFailed) {
                doneRef.current = true
                stopPolling()
                if (onCompletion) onCompletion()
            }
        } catch (err) {
            setError((err as Error).message)
            setLoading(false)
        }
    }, [parentTaskId, reactGrid, onCompletion])

    const toggleExpanded = React.useCallback(() => {
        setIsExpanded((prev) => !prev)
    }, [])

    React.useEffect(() => {
        defineGrid()
    }, [])

    React.useEffect(() => {
        if (isExpanded) {
            startPolling()
            setTimeout(() => {
                reactGrid?.slickGrid.resizeCanvas()
                reactGrid?.slickGrid.autosizeColumns()
            }, 50)
        }
    }, [isExpanded, startPolling])

    React.useEffect(() => {
        if (isExpanded) {
            fetchChildrenOnce()
        }
    }, [parentTaskId, isExpanded, fetchChildrenOnce])

    React.useEffect(() => {
        if (reactGrid) {
            reactGrid.slickGrid.invalidate()
            reactGrid.slickGrid.render()
        }
    }, [dataset, reactGrid])

    React.useEffect(() => {
        return () => {
            doneRef.current = true
            stopPolling()
        }
    }, [stopPolling])

    if (!gridOptions || !columnDefinitions.length) {
        return (
            <div className="d-flex align-items-center gap-2 py-3">
                <Spinner animation="border" size="sm" />
                <span>Loading grid...</span>
            </div>
        )
    }

    return (
        <div id={containerId} style={{ borderRadius: 8, width: '100%' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px' }}>
                <Button variant="link" size="sm" onClick={toggleExpanded}>
                    {isExpanded ? 'Hide ▴' : 'Show ▾'}
                </Button>
            </div>
            <Collapse in={isExpanded}>
                <div>
                    {loading && !isExpanded ? (
                        <div className="d-flex align-items-center gap-2 py-3">
                            <Spinner animation="border" size="sm" />
                            <span>Querying Ray cluster for task state...</span>
                        </div>
                    ) : error ? (
                        <div className="alert alert-danger py-2">{error}</div>
                    ) : dataset.length === 0 ? (
                        <div className="text-muted py-2">No child tasks found.</div>
                    ) : (
                        <div style={{ width: '100%' }}>
                            <SlickgridReact
                                gridId={`${containerId}-grid`}
                                columns={columnDefinitions}
                                options={gridOptions}
                                dataset={dataset}
                                onReactGridCreated={$event => reactGridReady($event.detail)}
                            />
                        </div>
                    )}
                </div>
            </Collapse>
        </div>
    )
}
