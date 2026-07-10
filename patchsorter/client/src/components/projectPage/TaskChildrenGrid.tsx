import { useState, useEffect, useCallback, useRef } from 'react'
import { Table, Spinner } from 'react-bootstrap'
import { searchRayTasks } from '../../api_client'

interface RayTaskState {
    task_id: string
    func_or_class_name: string
    state: string
    creation_time?: number | null
    end_time?: number | null
    error_message?: string | null
}

const POLL_INTERVAL_MS = 3000

interface TaskChildrenGridProps {
    parentTaskId: string
    onCompletion?: () => void
}

const STATE_COLORS: Record<string, string> = {
    PENDING: '#6c757d',
    RUNNING: '#0d6efd',
    DONE: '#198754',
    FAILED: '#dc3545',
    CANCELLED: '#6f42c1',
}

export default function TaskChildrenGrid({ parentTaskId, onCompletion }: TaskChildrenGridProps) {
    const [tasks, setTasks] = useState<RayTaskState[]>([])
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const doneRef = useRef(false)

    const poll = useCallback(async () => {
        if (doneRef.current) return
        try {
            const res = await searchRayTasks({
                body: [['parent_task_id', '=', parentTaskId]],
            })
            if (res.error) {
                if (res.error.status !== 404) {
                    setError(`Ray task query failed: ${res.error.statusText || 'Unknown error'}`)
                }
                setTasks([])
                setLoading(false)
                return
            }
            const result = res.data! as RayTaskState[]
            setTasks(result)
            setLoading(false)
            setError(null)

            if (result.length === 0) return

            const allDone = result.every(t => t.state === 'DONE')
            const anyFailed = result.some(t => t.state === 'FAILED')

            if (allDone || anyFailed) {
                doneRef.current = true
                if (onCompletion) onCompletion()
            }
        } catch (err) {
            setError((err as Error).message)
            setLoading(false)
        }
    }, [parentTaskId, onCompletion])

    useEffect(() => {
        poll()
        const interval = setInterval(poll, POLL_INTERVAL_MS)
        return () => {
            doneRef.current = true
            clearInterval(interval)
        }
    }, [poll])

    if (loading) {
        return (
            <div className="d-flex align-items-center gap-2 py-3">
                <Spinner animation="border" size="sm" />
                <span>Querying Ray cluster for task state...</span>
            </div>
        )
    }

    if (error) {
        return (
            <div className="alert alert-danger py-2">
                {error}
            </div>
        )
    }

    if (tasks.length === 0) {
        return (
            <div className="text-muted py-2">
                No child tasks found.
            </div>
        )
    }

    return (
        <Table striped bordered hover size="sm" className="mb-0">
            <thead>
                <tr>
                    <th>Task ID</th>
                    <th>Function</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Ended</th>
                    <th>Error</th>
                </tr>
            </thead>
            <tbody>
                {tasks.map(task => (
                    <tr key={task.task_id}>
                        <td
                            style={{
                                fontFamily: 'monospace',
                                fontSize: '0.8rem',
                                maxWidth: 160,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}
                            title={task.task_id}
                        >
                            {task.task_id.slice(0, 12)}...
                        </td>
                        <td>{task.func_or_class_name}</td>
                        <td>
                            <span
                                className="badge"
                                style={{
                                    backgroundColor: STATE_COLORS[task.state] || '#6c757d',
                                    color: task.state === 'RUNNING' ? '#fff' : undefined,
                                }}
                            >
                                {task.state}
                            </span>
                        </td>
                        <td>
                            {task.creation_time
                                ? new Date(task.creation_time).toLocaleTimeString()
                                : ''}
                        </td>
                        <td>
                            {task.end_time
                                ? new Date(task.end_time).toLocaleTimeString()
                                : ''}
                        </td>
                        <td
                            style={{
                                maxWidth: 200,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}
                            title={task.error_message || ''}
                        >
                            {task.error_message || '-'}
                        </td>
                    </tr>
                ))}
            </tbody>
        </Table>
    )
}
