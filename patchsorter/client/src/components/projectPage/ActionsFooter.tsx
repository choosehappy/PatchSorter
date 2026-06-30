import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from 'react-bootstrap'
import ConfirmationModal from '../ConfirmationModal'

interface ActionsFooterProps {
    projectId: number
    selectedImageIds: Set<number>
    selectedLabelClassIds: Set<number>
    onClearImageSelection: () => void
    onClearLabelClassSelection: () => void
}

export default function ActionsFooter({
    projectId,
    selectedImageIds,
    selectedLabelClassIds,
    onClearImageSelection,
    onClearLabelClassSelection,
}: ActionsFooterProps) {
    const navigate = useNavigate()
    const [confirmTarget, setConfirmTarget] = useState<'images' | 'labelClasses' | null>(null)

    const hasImages = selectedImageIds.size > 0
    const hasLabelClasses = selectedLabelClassIds.size > 0

    const clearAll = () => {
        onClearImageSelection()
        onClearLabelClassSelection()
    }

    return (
        <>
            <div
                style={{
                    position: 'fixed',
                    bottom: 0,
                    left: 0,
                    right: 0,
                    zIndex: 1000,
                    backgroundColor: '#fff',
                    borderTop: '1px solid #dee2e6',
                    boxShadow: '0 -2px 8px rgba(0,0,0,0.08)',
                    padding: '12px 24px',
                }}
            >
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
                    <div className="d-flex align-items-center gap-2 flex-wrap">
                        <Button
                            variant="primary"
                            size="sm"
                            onClick={() => navigate(`/project/${projectId}/labeler`)}
                        >
                            Open Labeler
                        </Button>

                        {hasImages && (
                            <>
                                <Button
                                    variant="outline-secondary"
                                    size="sm"
                                    onClick={() => setConfirmTarget('images')}
                                >
                                    Export Patches for {selectedImageIds.size} Image{selectedImageIds.size > 1 ? 's' : ''}
                                </Button>
                                <Button
                                    variant="outline-danger"
                                    size="sm"
                                    onClick={() => setConfirmTarget('images')}
                                >
                                    Delete {selectedImageIds.size} Image{selectedImageIds.size > 1 ? 's' : ''}
                                </Button>
                            </>
                        )}

                        {hasLabelClasses && (
                            <Button
                                variant="outline-danger"
                                size="sm"
                                onClick={() => setConfirmTarget('labelClasses')}
                            >
                                Delete {selectedLabelClassIds.size} Label Class{selectedLabelClassIds.size > 1 ? 'es' : ''}
                            </Button>
                        )}
                    </div>

                    {(hasImages || hasLabelClasses) && (
                        <Button
                            variant="link"
                            size="sm"
                            onClick={clearAll}
                            style={{ textDecoration: 'none' }}
                        >
                            Clear selection
                        </Button>
                    )}
                </div>
            </div>

            {confirmTarget === 'images' && (
                <ConfirmationModal
                    show={confirmTarget === 'images'}
                    message={`Delete ${selectedImageIds.size} image${selectedImageIds.size > 1 ? 's' : ''}? This action cannot be undone.`}
                    onConfirm={() => {
                        console.log('Delete images not implemented yet')
                        setConfirmTarget(null)
                    }}
                    onCancel={() => setConfirmTarget(null)}
                />
            )}

            {confirmTarget === 'labelClasses' && (
                <ConfirmationModal
                    show={confirmTarget === 'labelClasses'}
                    message={`Delete ${selectedLabelClassIds.size} label class${selectedLabelClassIds.size > 1 ? 'es' : ''}? This action cannot be undone.`}
                    onConfirm={() => {
                        console.log('Delete label classes not implemented yet')
                        setConfirmTarget(null)
                    }}
                    onCancel={() => setConfirmTarget(null)}
                />
            )}
        </>
    )
}
