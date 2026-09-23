import { useRef, useEffect } from 'react'
import { Modal, Button, Form } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { useMutation } from '@tanstack/react-query'
import type { ProjectResponse } from '../../api_client'
import { updateProjectProjectsProjectIdPut } from '../../api_client'

interface EditProjectModalProps {
    show: boolean
    project: ProjectResponse | null
    onClose: () => void
    onSuccess: () => void
}

export default function EditProjectModal({ show, project, onClose, onSuccess }: EditProjectModalProps) {
    const nameRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        if (show && project && nameRef.current) {
            nameRef.current.value = project.project_name
            setTimeout(() => nameRef.current?.focus(), 100)
        }
    }, [show, project])

    const mutation = useMutation({
        mutationFn: (vars: { name: string; description: string | null }) =>
            updateProjectProjectsProjectIdPut({
                path: { project_id: project!.project_id },
                body: { name: vars.name, description: vars.description },
            }),
        onSuccess: () => {
            toast.success('Project updated successfully.')
            onClose()
            onSuccess()
        },
        onError: (err: unknown) => {
            const detail = (err as any)?.detail
            toast.error(detail ? `Failed to update project: ${detail}` : 'Failed to update project. Please try again.')
        },
    })

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (!project) return
        const form = e.currentTarget
        const name = (form.elements.namedItem('projectName') as HTMLInputElement).value.trim()
        const description = (form.elements.namedItem('projectDescription') as HTMLTextAreaElement).value.trim() || null
        if (!name) {
            toast.error('Project name is required.')
            return
        }
        mutation.mutate({ name, description })
    }

    return (
        <Modal show={show} onHide={onClose} centered size="lg">
            <Modal.Header closeButton>
                <Modal.Title>Edit Project</Modal.Title>
            </Modal.Header>
            <Form onSubmit={handleSubmit}>
                <Modal.Body>
                    <Form.Group className="mb-3">
                        <Form.Label>Project Name <span className="text-danger">*</span></Form.Label>
                        <Form.Control
                            ref={nameRef}
                            name="projectName"
                            type="text"
                            defaultValue={project?.project_name ?? ''}
                            placeholder="Enter project name"
                            required
                        />
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>Description</Form.Label>
                        <Form.Control
                            as="textarea"
                            name="projectDescription"
                            rows={3}
                            defaultValue={project?.description ?? ''}
                            placeholder="Optional description"
                        />
                    </Form.Group>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
                        Cancel
                    </Button>
                    <Button variant="primary" type="submit" disabled={mutation.isPending}>
                        {mutation.isPending ? (
                            <>
                                <span className="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true" />
                                Updating…
                            </>
                        ) : (
                            'Save Changes'
                        )}
                    </Button>
                </Modal.Footer>
            </Form>
        </Modal>
    )
}
