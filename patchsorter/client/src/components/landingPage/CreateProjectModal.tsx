import { useRef, useEffect, useState } from 'react'
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
    const [patchExtractionMethod, setPatchExtractionMethod] = useState('use manual object radius')

    useEffect(() => {
        if (show) {
            if (nameInputRef.current) nameInputRef.current.value = ''
            if (descriptionRef.current) descriptionRef.current.value = ''
            setTimeout(() => nameRef.current?.focus(), 100)
        }
    }, [show])

    const mutation = useMutation({
        mutationFn: (vars: { name: string; description: string | null; patch_size?: number; patch_extraction_method?: string; object_radius?: number }) =>
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
        const patchSizeVal = (form.elements.namedItem('patchSize') as HTMLInputElement).value
        const objectRadiusVal = (form.elements.namedItem('objectRadius') as HTMLInputElement).value
        const patch_size = patchSizeVal ? parseInt(patchSizeVal, 10) : undefined
        const object_radius = objectRadiusVal ? parseInt(objectRadiusVal, 10) : undefined
        if (!name) {
            toast.error('Project name is required.')
            return
        }
        mutation.mutate({ name, description, patch_size, patch_extraction_method: patchExtractionMethod, object_radius })
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
                    <hr className="my-4" />
                    <h6 className="mb-3">Project Configuration</h6>
                    <Form.Group className="mb-3">
                        <Form.Label>Patch Size (pixels)</Form.Label>
                        <Form.Control
                            name="patchSize"
                            type="number"
                            defaultValue="64"
                            placeholder="64"
                        />
                        <Form.Text className="text-muted">Size of each patch in pixels</Form.Text>
                    </Form.Group>
                    <Form.Group className="mb-3">
                        <Form.Label>Patch Extraction Method</Form.Label>
                        <Form.Control
                            as="select"
                            defaultValue="use manual object radius"
                            onChange={(e) => setPatchExtractionMethod(e.target.value)}
                        >
                            <option value="use manual object radius">use manual object radius</option>
                        </Form.Control>
                        <Form.Text className="text-muted">Method for extracting patches from tissue objects</Form.Text>
                    </Form.Group>
                    {patchExtractionMethod === 'use manual object radius' && (
                        <Form.Group className="mb-3">
                            <Form.Label>Object Radius (microns)</Form.Label>
                            <Form.Control
                                name="objectRadius"
                                type="number"
                                defaultValue="10"
                                placeholder="10"
                            />
                            <Form.Text className="text-muted">Expected radius of an object in microns</Form.Text>
                        </Form.Group>
                    )}
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
