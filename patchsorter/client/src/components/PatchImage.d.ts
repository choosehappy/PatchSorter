import './patchGallery.css';
interface PatchImageProps {
    projectId: number;
    patchId: number;
    gtLabelClassId: number;
    predLabelClassId: number | null;
    isSelected: boolean;
}
export default function PatchImage({ projectId, patchId, gtLabelClassId, predLabelClassId, isSelected }: PatchImageProps): import("react/jsx-runtime").JSX.Element;
export {};
