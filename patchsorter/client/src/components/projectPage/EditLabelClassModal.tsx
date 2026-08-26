import { useState, useEffect } from 'react'
import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { updateLabelClassProjectsProjectIdLabelClassesLabelClassIdPut, type LabelClassResponse } from '../../api_client'

interface EditLabelClassModalProps {
    projectId: number
    labelClass: LabelClassResponse
    show: boolean
    onClose: () => void
    onSuccess: () => void
}

export default function EditLabelClassModal({ projectId, labelClass, show, onClose, onSuccess }: EditLabelClassModalProps) {
    const [name, setName] = useState('')
    const [colorCode, setColorCode] = useState('#000000')
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (show) {
            setName(labelClass.name)
            setColorCode(labelClass.color_code ?? '#000000')
        }
    }, [show, labelClass])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!name.trim()) {
            toast.error('Name is required')
            return
        }
        setSaving(true)
        try {
            await updateLabelClassProjectsProjectIdLabelClassesLabelClassIdPut({
                path: { project_id: projectId, label_class_id: labelClass.label_class_id },
                body: { name: name.trim(), color_code: colorCode },
            })
            toast.success('Label class updated successfully')
            onSuccess()
            onClose()
        } catch (err: any) {
            const detail = err?.body?.detail || 'Failed to update label class'
            toast.error(`Error: ${detail}`)
        } finally {
            setSaving(false)
        }
    }

    return (
        <Modal show={show} onHide={onClose} centered>
            <Modal.Header closeButton>
                <Modal.Title>Edit Label Class</Modal.Title>
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
                            placeholder="e.g. Nucleus, Cytoplasm"
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
                        {saving ? 'Saving...' : 'Save'}
                    </Button>
                </Modal.Footer>
            </form>
        </Modal>
    )
}
