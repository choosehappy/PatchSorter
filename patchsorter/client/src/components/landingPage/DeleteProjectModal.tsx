import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { useMutation } from '@tanstack/react-query'
import type { ProjectResponse } from '../../api_client'
import { deleteProjectProjectsProjectIdDelete } from '../../api_client'

interface DeleteProjectModalProps {
    show: boolean
    project: ProjectResponse | null
    onClose: () => void
    onSuccess: () => void
}

export default function DeleteProjectModal({ show, project, onClose, onSuccess }: DeleteProjectModalProps) {
    const mutation = useMutation({
        mutationFn: () =>
            deleteProjectProjectsProjectIdDelete({
                path: { project_id: project!.project_id },
            }),
        onSuccess: () => {
            toast.success('Project deleted successfully.')
            onClose()
            onSuccess()
        },
        onError: (err: unknown) => {
            const detail = (err as any)?.detail
            toast.error(detail ? `Failed to delete project: ${detail}` : 'Failed to delete project. Please try again.')
        },
    })

    if (!project) return null

    return (
        <Modal show={show} onHide={onClose} centered>
            <Modal.Header closeButton>
                <Modal.Title>Delete Project</Modal.Title>
            </Modal.Header>
            <Modal.Body>
                <p>
                    Are you sure you want to delete the project{' '}
                    <strong>{project.project_name}</strong>?
                </p>
                <p className="text-danger">
                    This action cannot be undone. All project data, images, and settings will be permanently removed.
                </p>
            </Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
                    Cancel
                </Button>
                <Button variant="danger" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                    {mutation.isPending ? (
                        <>
                            <span className="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true" />
                            Deleting…
                        </>
                    ) : (
                        'Delete Project'
                    )}
                </Button>
            </Modal.Footer>
        </Modal>
    )
}
