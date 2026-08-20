import React from 'react'

interface StepIndicatorProps {
    steps: string[]
    currentStep: number  // position within the steps array (0-indexed)
}

export default function UploadStepIndicator({ steps, currentStep }: StepIndicatorProps) {
    return (
        <div className="d-flex flex-wrap align-items-center gap-1 mb-3" style={{ fontSize: '0.85rem' }}>
            {steps.map((label, idx) => (
                <React.Fragment key={idx}>
                    {idx > 0 && (
                        <span className="text-muted" aria-hidden="true" style={{ userSelect: 'none' }}>
                            •
                        </span>
                    )}
                    <span
                        className={[
                            'upload-step-segment',
                            idx === currentStep ? 'current' : idx < currentStep ? 'done' : 'upcoming',
                        ].join(' ')}
                    >
                        {idx + 1}. {label}
                    </span>
                </React.Fragment>
            ))}
        </div>
    )
}
