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

    return (
        <div className="d-inline-flex align-items-start flex-column gap-1">
            <button
                className={`btn btn-sm ${isActive ? 'btn-success' : 'btn-outline-secondary'}`}
                disabled={lifecycleMutation.isPending}
                onClick={() => lifecycleMutation.mutate(!isActive)}
            >
                {lifecycleMutation.isPending ? (
                    <><Spinner animation="border" size="sm" className="me-1" />Updating…</>
                ) : (
                    isActive ? 'DL: Active' : 'DL: Inactive'
                )}
            </button>

            {/* Freeze toggle — only shown when actor is active */}
            {isActive && (
                <div className="ms-2 ps-2 border-start">
                    <button
                        className={`btn btn-sm ${isFrozen ? 'btn-warning' : 'btn-outline-primary'}`}
                        disabled={freezeMutation.isPending}
                        onClick={() => freezeMutation.mutate(!isFrozen)}
                    >
                        {freezeMutation.isPending ? 'Updating…' : isFrozen ? 'Frozen' : 'Training'}
                    </button>
                </div>
            )}

            {(lifecycleMutation.isError || freezeMutation.isError) && (
                <span className="text-danger" style={{ fontSize: 12 }}>Update failed</span>
            )}
        </div>
    )
}
