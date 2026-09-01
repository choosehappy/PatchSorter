import type { ReactNode } from 'react'

interface StepDescriptionProps {
    children: ReactNode
}

export default function StepDescription({ children }: StepDescriptionProps) {
    return (
        <p className="text-muted mb-2" style={{ fontSize: '0.875rem' }}>
            {children}
        </p>
    )
}
