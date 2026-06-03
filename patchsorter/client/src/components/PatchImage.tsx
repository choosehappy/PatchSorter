import { useState, useEffect } from 'react'
import { client } from '../api_client/client.gen'
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
    projectId: number
    patchId: number
    gtLabelClassId: number
    predLabelClassId: number | null
    isSelected: boolean
}

function getColor(id: number): string {
    if (id < 0 || id >= CLASS_COLORS.length) return '#cccccc'
    return CLASS_COLORS[id]
}

export default function PatchImage({ projectId, patchId, gtLabelClassId, predLabelClassId, isSelected }: PatchImageProps) {
    const [imageSrc, setImageSrc] = useState<string | null>(null)
    const [imageError, setImageError] = useState(false)

    useEffect(() => {
        let cancelled = false
        const fetchImage = async () => {
            try {
                const res = await client.get({
                    path: { project_id: projectId, patch_id: patchId },
                    url: '/projects/{project_id}/patches/{patch_id}/image',
                })
                if (!cancelled && res.data) {
                    const blob = res.data as Blob
                    const url = URL.createObjectURL(blob)
                    setImageSrc(url)
                }
            } catch (err) {
                console.error('Failed to fetch patch image:', err)
                setImageError(true)
            }
        }
        fetchImage()
        return () => {
            cancelled = true
        }
    }, [projectId, patchId])

    const outerBorderColor = predLabelClassId !== null ? getColor(predLabelClassId) : '#cccccc'
    const innerBorderColor = getColor(gtLabelClassId)

    const borderStyle = isSelected
        ? `6px dotted #4a90d9, 3px solid ${outerBorderColor}, 3px solid ${innerBorderColor}`
        : `3px solid ${outerBorderColor}, 3px solid ${innerBorderColor}`

    const placeholderStyle = {
        width: '100%',
        aspectRatio: '1',
        background: '#f0f0f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: borderStyle,
    }

    return (
        <div className="patch-image-wrapper">
            {imageSrc ? (
                <img
                    src={imageSrc}
                    alt={`patch gt=${gtLabelClassId} pred=${predLabelClassId ?? 'none'}`}
                    className="patch-image"
                    style={{ border: borderStyle }}
                    onLoad={() => {
                        // Clean up object URL when image is loaded to avoid memory leaks
                        // Note: we keep the URL until the component unmounts
                    }}
                    onError={() => setImageError(true)}
                />
            ) : (
                <div style={placeholderStyle}>
                    {imageError ? 'Image not available' : 'Loading...'}
                </div>
            )}
        </div>
    )
}
