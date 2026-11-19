import { useState, useEffect, useRef } from 'react'
import { getPatchContextProjectsProjectIdPatchesPatchIdContextGet } from '../api_client'
import type { PatchResponse } from '../api_client'
import './patchGallery.css'

interface PatchContextOverlayProps {
    projectId: number
    patch: PatchResponse
    mouseX: number
    mouseY: number
    scale: number
}

export default function PatchContextOverlay({
    projectId,
    patch,
    mouseX,
    mouseY,
    scale,
}: PatchContextOverlayProps) {
    const [imageSrc, setImageSrc] = useState<string | null>(null)
    const [imageError, setImageError] = useState(false)
    const overlayRef = useRef<HTMLDivElement>(null)
    const IMG_SIZE = 256

    useEffect(() => {
        const controller = new AbortController()
        const fetchContext = async () => {
            try {
                const res = await getPatchContextProjectsProjectIdPatchesPatchIdContextGet({
                    path: { project_id: projectId, patch_id: patch.patch_id },
                    query: { scale },
                    signal: controller.signal,
                })
                if (res.data) {
                    setImageSrc(URL.createObjectURL(res.data as Blob))
                }
            } catch (err: any) {
                if (err.name === 'AbortError') return
                console.error('Failed to fetch patch context:', err)
                setImageError(true)
            }
        }
        fetchContext()
        return () => controller.abort()
    }, [projectId, patch.patch_id, scale])

    // Second useEffect is registered to clean up the object URL when it changes or on unmount
    useEffect(() => {
        if (!imageSrc) return
        return () => URL.revokeObjectURL(imageSrc)
    }, [imageSrc])

    useEffect(() => {
        if (!overlayRef.current || !imageSrc) return
        const rect = overlayRef.current.getBoundingClientRect()
        let left = mouseX + 16
        let top = mouseY + 16

        if (left + IMG_SIZE > window.innerWidth) {
            left = mouseX - IMG_SIZE - 16
        }
        if (top + IMG_SIZE > window.innerHeight) {
            top = mouseY - IMG_SIZE - 16
        }

        overlayRef.current.style.left = `${left}px`
        overlayRef.current.style.top = `${top}px`
    }, [mouseX, mouseY, imageSrc])

    if (imageError || !imageSrc) {
        return null
    }

    return (
        <div
            ref={overlayRef}
            className="patch-context-overlay"
            style={{ width: IMG_SIZE, height: IMG_SIZE }}
        >
            <img
                src={imageSrc}
                alt={`Context around patch ${patch.patch_id}`}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
        </div>
    )
}
