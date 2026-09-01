import { useRef, useEffect } from 'react'
import { Modal, Button, Form } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { useMutation } from '@tanstack/react-query'
import { createProjectProjectsPost } from '../../api_client'

interface CreateProjectModalProps {
    show: boolean
    onClose: () => void
    onSuccess: () => void
}

export default function CreateProjectModal({ show, onClose, onSuccess }: CreateProjectModalProps) {
    const nameRef = useRef<HTMLInputElement>(null)
    const nameInputRef = useRef<HTMLInputElement>(null)
    const descriptionRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        if (show) {
            if (nameInputRef.current) nameInputRef.current.value = ''
            if (descriptionRef.current) descriptionRef.current.value = ''
            setTimeout(() => nameRef.current?.focus(), 100)
        }
    }, [show])

    const mutation = useMutation({
        mutationFn: (vars: { name: string; description: string | null }) =>
            createProjectProjectsPost({ body: vars }),
        onSuccess: () => {
            toast.success('Project created successfully.')
            onClose()
            onSuccess()
        },
        onError: (err: unknown) => {
            const detail = (err as any)?.detail
            toast.error(detail ? `Failed to create project: ${detail}` : 'Failed to create project. Please try again.')
        },
    })

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault()
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
                <Modal.Title>Create New Project</Modal.Title>
            </Modal.Header>
            <Form onSubmit={handleSubmit}>
                <Modal.Body>
                    <Form.Group className="mb-3">
                        <Form.Label>Project Name <span className="text-danger">*</span></Form.Label>
                        <Form.Control
                            ref={nameRef}
                            name="projectName"
                            type="text"
                            defaultValue=""
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
                            defaultValue=""
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
                                Creating…
                            </>
                        ) : (
                            'Create Project'
                        )}
                    </Button>
                </Modal.Footer>
            </Form>
        </Modal>
    )
}
