import './patchGallery.css';
import type { PatchResponse } from '../api_client';
export default function PatchGallery({ projectId, patchGalleryItems, }: {
    projectId: number;
    patchGalleryItems: PatchResponse[] | null;
}): import("react/jsx-runtime").JSX.Element;
