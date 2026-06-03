import './patchGallery.css';
interface PatchImageProps {
    patchImageBase64: string;
    gtLabelClassId: number;
    predLabelClassId: number | null;
    isSelected: boolean;
}
export default function PatchImage({ patchImageBase64, gtLabelClassId, predLabelClassId, isSelected }: PatchImageProps): import("react/jsx-runtime").JSX.Element;
export {};
