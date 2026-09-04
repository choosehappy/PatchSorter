import { useState } from 'react'
import { Spinner } from 'react-bootstrap'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDlActorState, startProcessing, requestShutdown, setDlActorFreeze } from '../../api_client/sdk.gen'
import type { DlActorState } from '../../api_client/types.gen'

interface DLActorControlProps {
    projectId: number
    pollIntervalMs?: number
}

export default function DLActorControl({ projectId, pollIntervalMs = 3000 }: DLActorControlProps) {
    const queryClient = useQueryClient()
    const [lifecycleHover, setLifecycleHover] = useState(false)
    const [freezeHover, setFreezeHover] = useState(false)

    const { data: state } = useQuery<DlActorState | null>({
        queryKey: ['dlActorState', projectId],
        queryFn: () =>
            getDlActorState({ path: { project_id: projectId } }).then(r => r.data ?? null),
        refetchInterval: pollIntervalMs,
    })

    const lifecycleMutation = useMutation({
        mutationFn: (activate: boolean) =>
            activate
                ? startProcessing({ path: { project_id: projectId } })
                : requestShutdown({ path: { project_id: projectId } }),
        onSuccess: () =>
            queryClient.invalidateQueries({ queryKey: ['dlActorState', projectId] }),
    })

    const freezeMutation = useMutation({
        mutationFn: (frozen: boolean) =>
            setDlActorFreeze({ path: { project_id: projectId }, query: { frozen } }).then(
                r => r.data!,
            ),
        onSuccess: newState =>
            queryClient.setQueryData(['dlActorState', projectId], newState),
    })

    const isActive = state !== null && state !== undefined && !state.termination_signal
    const isFrozen = isActive && !state!.training_enabled

    const lifecycleLabel = lifecycleMutation.isPending
        ? 'Updating…'
        : lifecycleHover
        ? (isActive ? 'Terminate' : 'Activate')
        : (isActive ? 'DL: Ready' : 'DL: Not Ready')

    const freezeLabel = freezeMutation.isPending
        ? 'Updating…'
        : freezeHover
        ? (isFrozen ? 'Unfreeze' : 'Freeze')
        : (isFrozen ? 'Frozen' : 'Training')

    return (
        <div
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 12,
                padding: '8px 14px',
                border: '1px solid #dee2e6',
                borderRadius: 8,
                backgroundColor: '#f8f9fa',
                transition: 'width 0.3s ease, min-width 0.3s ease',
                minWidth: isActive ? 140 : 110,
            }}
        >
            <button
                className={`btn btn-sm ${isActive ? 'btn-success' : 'btn-outline-secondary'}`}
                disabled={lifecycleMutation.isPending}
                onClick={() => lifecycleMutation.mutate(!isActive)}
                onMouseEnter={() => setLifecycleHover(true)}
                onMouseLeave={() => setLifecycleHover(false)}
            >
                {lifecycleMutation.isPending && <Spinner animation="border" size="sm" className="me-1" />}
                {lifecycleLabel}
            </button>

            {/* Freeze toggle — only shown when actor is active */}
            {isActive && (
                <button
                    className={`btn btn-sm ${isFrozen ? 'btn-warning' : 'btn-outline-primary'}`}
                    disabled={freezeMutation.isPending}
                    onClick={() => freezeMutation.mutate(!isFrozen)}
                    onMouseEnter={() => setFreezeHover(true)}
                    onMouseLeave={() => setFreezeHover(false)}
                >
                    {freezeLabel}
                </button>
            )}

            {(lifecycleMutation.isError || freezeMutation.isError) && (
                <span className="text-danger" style={{ fontSize: 12 }}>Update failed</span>
            )}
        </div>
    )
}