import { Button } from 'react-bootstrap'

interface LandingActionsFooterProps {
    onCreateProject: () => void
}

export default function LandingActionsFooter({ onCreateProject }: LandingActionsFooterProps) {
    return (
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
            <div className="d-flex align-items-center gap-2 flex-wrap">
                <Button variant="primary" size="sm" onClick={onCreateProject}>
                    Create New Project
                </Button>
            </div>
        </div>
    )
}
