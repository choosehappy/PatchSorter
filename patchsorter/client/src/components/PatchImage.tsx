import { useState, useEffect } from 'react'
import { client } from '../api_client/client.gen'
import './patchGallery.css'
import type { PatchResponse, LabelClassResponse } from '../api_client'

interface PatchImageProps {
    projectId: number
    patch: PatchResponse
    labelClasses: LabelClassResponse[]
    isSelected: boolean
}

function getLabelColor(labelClassId: number | null, labelClasses: LabelClassResponse[]): string {
    if (labelClassId === null || labelClassId < 0) return '#cccccc'
    const labelClass = labelClasses.find(lc => lc.label_class_id === labelClassId)
    if (labelClass) {
        return labelClass.color_code ?? '#cccccc'
    }
    return '#cccccc'
}

export default function PatchImage({ projectId, patch, labelClasses, isSelected }: PatchImageProps) {
    const [imageSrc, setImageSrc] = useState<string | null>(null)
    const [imageError, setImageError] = useState(false)

    useEffect(() => {
        let cancelled = false
        const fetchImage = async () => {
            try {
                const res = await client.get({
                    path: { project_id: projectId, patch_id: patch.patch_id },
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
    }, [projectId, patch.patch_id])

    const outerBorderColor = getLabelColor(patch.pred_label_class_id ?? null, labelClasses)
    const innerBorderColor = getLabelColor(patch.label_class_id, labelClasses)

    const outerBorder = isSelected ? `3px dashed ${outerBorderColor}` : `3px solid ${outerBorderColor}`
    const innerBorder = isSelected ? `3px dashed ${innerBorderColor}` : `3px solid ${innerBorderColor}`

    const wrapperStyle = {
        border: outerBorder,
        borderRadius: '0px',
        background: '#f0f0f0',
    }

    const middleStyle = {
        border: '1px solid #ffffff',
        borderRadius: '0px',
        width: '100%',
        aspectRatio: '1',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        boxSizing: 'border-box',
    }

    const innerWrapperStyle = {
        border: innerBorder,
        borderRadius: '0px',
        width: '100%',
        aspectRatio: '1',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        boxSizing: 'border-box',
    }

    return (
        <div className="patch-image-wrapper" style={wrapperStyle}>
            <div style={middleStyle}>
                <div style={innerWrapperStyle}>
                    {imageSrc ? (
                        <img
                            src={imageSrc}
                            alt={`patch gt=${patch.label_class_id} pred=${patch.pred_label_class_id ?? 'none'}`}
                            className="patch-image"
                            onLoad={() => {
                                // Clean up object URL when image is loaded to avoid memory leaks
                                // Note: we keep the URL until the component unmounts
                            }}
                            onError={() => setImageError(true)}
                        />
                    ) : (
                        <span>{imageError ? 'Image not available' : 'Loading...'}</span>
                    )}
                </div>
            </div>
        </div>
    )
}
