import './patchGallery.css';
import type { PatchResponse, LabelClassResponse } from '../api_client';
interface PatchImageProps {
    projectId: number;
    patch: PatchResponse;
    labelClasses: LabelClassResponse[];
    isSelected: boolean;
}
export default function PatchImage({ projectId, patch, labelClasses, isSelected }: PatchImageProps): import("react/jsx-runtime").JSX.Element;
export {};
