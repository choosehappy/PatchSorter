import { useState, useEffect } from 'react'
import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { createLabelClassProjectsProjectIdLabelClassesPost, getDefaultLabelClassProjectsProjectIdLabelClassesDefaultGet } from '../../api_client'

interface CreateLabelClassModalProps {
    projectId: number
    show: boolean
    onClose: () => void
    onSuccess: () => void
}

export default function CreateLabelClassModal({ projectId, show, onClose, onSuccess }: CreateLabelClassModalProps) {
    const [name, setName] = useState('')
    const [colorCode, setColorCode] = useState('#000000')
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (show) {
            getDefaultLabelClassProjectsProjectIdLabelClassesDefaultGet({
                path: { project_id: projectId },
            })
                .then(r => {
                    if (r.data?.color_code) {
                        setColorCode(r.data.color_code)
                    }
                })
                .catch(() => {
                    setColorCode('#000000')
                })
        }
    }, [show, projectId])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!name.trim()) {
            toast.error('Name is required')
            return
        }
        setSaving(true)
        const result = await createLabelClassProjectsProjectIdLabelClassesPost({
            path: { project_id: projectId },
            body: { name: name.trim(), color_code: colorCode },
        })
        setSaving(false)
        if (result.error) {
            const detail = result.error?.body?.detail || 'Failed to create label class'
            toast.error(`Error: ${detail}`)
        } else {
            toast.success('Label class created successfully')
            setName('')
            setColorCode('#000000')
            onSuccess()
            onClose()
        }
    }

    return (
        <Modal show={show} onHide={onClose} centered>
            <Modal.Header closeButton>
                <Modal.Title>Create Label Class</Modal.Title>
            </Modal.Header>
            <form onSubmit={handleSubmit}>
                <Modal.Body>
                    <div className="mb-3">
                        <label htmlFor="lc-name" className="form-label">
                            Name
                        </label>
                        <input
                            type="text"
                            className="form-control"
                            id="lc-name"
                            value={name}
                            onChange={e => setName(e.target.value)}
                            placeholder="e.g. Label class 1, Lymphocyte, Tubule, Benign, etc."
                        />
                    </div>
                    <div className="mb-3">
                        <label htmlFor="lc-color" className="form-label">
                            Color
                        </label>
                        <div className="d-flex align-items-center gap-2">
                            <input
                                type="color"
                                className="form-control form-control-color"
                                id="lc-color"
                                value={colorCode}
                                onChange={e => setColorCode(e.target.value)}
                                title="Choose a color"
                            />
                            <span className="text-muted">{colorCode}</span>
                        </div>
                    </div>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </Button>
                    <Button variant="primary" type="submit" disabled={saving || !name.trim()}>
                        {saving ? 'Creating...' : 'Create'}
                    </Button>
                </Modal.Footer>
            </form>
        </Modal>
    )
}
