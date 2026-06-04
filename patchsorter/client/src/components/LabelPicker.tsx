import { useEffect, useCallback, useMemo } from 'react'
import type { LabelClassResponse } from '../api_client'
import './labelPicker.css'

interface LabelPickerProps {
    isOpen: boolean
    labelClasses: LabelClassResponse[]
    onSelect: (labelClassId: number) => void
    onClose: () => void
}

export default function LabelPicker({ isOpen, labelClasses, onSelect, onClose }: LabelPickerProps) {
    const sorted = useMemo(
        () => [...labelClasses].sort((a, b) => a.label_class_id - b.label_class_id),
        [labelClasses]
    )

    const handleBackdropClick = useCallback(() => {
        onClose()
    }, [onClose])

    const handleKeyDown = useCallback((e: KeyboardEvent) => {
        if (!isOpen) return

        if (e.key === 'Escape') {
            onClose()
            return
        }

        const num = parseInt(e.key, 10)
        if (num >= 1 && num <= 9 && num <= sorted.length) {
            onSelect(sorted[num - 1].label_class_id)
            onClose()
        }
    }, [isOpen, onClose, onSelect, sorted])

    useEffect(() => {
        if (!isOpen) return
        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [isOpen, handleKeyDown])

    if (!isOpen) return null

    return (
        <div className="label-picker-overlay" onClick={handleBackdropClick}>
            <div className="label-picker-card" onClick={e => e.stopPropagation()}>
                <span className="label-picker-hint">Esc to close</span>
                <span className="label-picker-hint-bottom">Press <kbd>numKey</kbd> or click a class to assign it to the selected patches</span>
                {sorted.map((lc, i) => (
                    <button
                        key={lc.label_class_id}
                        className="label-picker-row"
                        onClick={() => {
                            onSelect(lc.label_class_id)
                            onClose()
                        }}
                    >
                        <span className="label-picker-index">{i + 1}</span>
                        <span
                            className="label-picker-swatch"
                            style={{ backgroundColor: lc.color_code ?? '#cccccc' }}
                        />
                        <span className="label-picker-name">{lc.name}</span>
                    </button>
                ))}
            </div>
        </div>
    )
}
