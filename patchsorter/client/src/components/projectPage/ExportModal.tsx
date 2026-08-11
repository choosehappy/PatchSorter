import { useState, useCallback } from 'react'
import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import { exportPatchCsv, type ExportResponse } from '../../api_client'

interface ExportModalProps {
    projectId: number
    selectedImageIds: Set<number>
    onClose: () => void
    onExportStarted?: (data: { task_id: string; manifest_urls: string[] }) => void
    onExportComplete?: (urls: string[]) => void
}

export default function ExportModal({ projectId, selectedImageIds, onClose, onExportStarted, onExportComplete }: ExportModalProps) {
    const [isExporting, setIsExporting] = useState(false)

    const handleExport = useCallback(async () => {
        setIsExporting(true)
        try {
            const res = await exportPatchCsv({
                path: { project_id: projectId },
                body: { image_ids: [...selectedImageIds] },
            })

            if (res.error) {
                const detail = (res.error as any)?.detail
                toast.error(detail ? `Export error: ${detail}` : 'Failed to start export. Please try again.')
                setIsExporting(false)
                return
            }

            const data = res.data as ExportResponse
            if (!data?.task_id) {
                toast.error('Export failed: no task_id returned.')
                setIsExporting(false)
                return
            }

            if (onExportStarted) {
                onExportStarted({ task_id: data.task_id, manifest_urls: data.manifest_urls ?? [] })
            }
            onExportComplete?.(data.manifest_urls ?? [])
            onClose()
        } catch (err) {
            console.error('Export failed:', err)
            toast.error('Failed to start export. Please try again.')
            setIsExporting(false)
        }
    }, [projectId, selectedImageIds, onClose, onExportStarted, onExportComplete])

    return (
        <Modal show onHide={onClose} centered>
            <Modal.Header closeButton>
                <Modal.Title>Export Patch Labels</Modal.Title>
            </Modal.Header>
            <Modal.Body>
                <p>
                    Export patch labels for {selectedImageIds.size} image{selectedImageIds.size > 1 ? 's' : ''}?
                </p>
            </Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={onClose} disabled={isExporting}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    onClick={handleExport}
                    disabled={isExporting}
                >
                    {isExporting ? (
                        <>
                            <span
                                className="spinner-border spinner-border-sm me-2"
                                role="status"
                                aria-hidden="true"
                            />
                            Confirm Export…
                        </>
                    ) : (
                        'Confirm Export'
                    )}
                </Button>
            </Modal.Footer>
        </Modal>
    )
}
