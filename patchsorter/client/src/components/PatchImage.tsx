import { useMemo } from 'react'
import './patchGallery.css'

const CLASS_COLORS = [
    '#222222',  // Unlabeled
    '#e41a1c',  // Class 1
    '#377eb8',  // Class 2
    '#ff7f00',  // Class 3
    '#984ea3',  // Class 4
    '#4daf4a',  // Class 5
    '#ffff33',  // Class 6
    '#a65628',  // Class 7
    '#f781bf',  // Class 8
    '#999999',  // Class 9
]

interface PatchImageProps {
    patchImageBase64: string
    gtLabelClassId: number
    predLabelClassId: number | null
    isSelected: boolean
}

function getColor(id: number): string {
    if (id < 0 || id >= CLASS_COLORS.length) return '#cccccc'
    return CLASS_COLORS[id]
}

export default function PatchImage({ patchImageBase64, gtLabelClassId, predLabelClassId, isSelected }: PatchImageProps) {
    const innerBorderColor = getColor(gtLabelClassId)
    const outerBorderColor = predLabelClassId !== null ? getColor(predLabelClassId) : '#cccccc'

    const borderStyle = isSelected
        ? `6px dotted #4a90d9, 3px solid ${outerBorderColor}, 3px solid ${innerBorderColor}`
        : `3px solid ${outerBorderColor}, 3px solid ${innerBorderColor}`

    return (
        <div className="patch-image-wrapper">
            <img
                src={`data:image/png;base64,${patchImageBase64}`}
                alt={`patch gt=${gtLabelClassId} pred=${predLabelClassId ?? 'none'}`}
                className="patch-image"
                style={{ border: borderStyle }}
            />
        </div>
    )
}
