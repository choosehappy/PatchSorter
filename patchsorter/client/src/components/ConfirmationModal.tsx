import { Button, Modal } from 'react-bootstrap'

interface ConfirmationModalProps {
    show: boolean
    message: string
    onConfirm: () => void
    onCancel: () => void
}

export default function ConfirmationModal({ show, message, onConfirm, onCancel }: ConfirmationModalProps) {
    return (
        <Modal show={show} onHide={onCancel} centered>
            <Modal.Header closeButton><Modal.Title>Confirm</Modal.Title></Modal.Header>
            <Modal.Body>{message}</Modal.Body>
            <Modal.Footer>
                <Button variant="secondary" onClick={onCancel}>Cancel</Button>
                <Button variant="danger" onClick={onConfirm}>Confirm</Button>
            </Modal.Footer>
        </Modal>
    )
}
