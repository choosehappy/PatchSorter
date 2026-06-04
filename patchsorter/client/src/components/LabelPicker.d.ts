import type { LabelClassResponse } from '../api_client';
import './labelPicker.css';
interface LabelPickerProps {
    isOpen: boolean;
    labelClasses: LabelClassResponse[];
    onSelect: (labelClassId: number) => void;
    onClose: (labelClassId: number | null) => void;
}
export default function LabelPicker({ isOpen, labelClasses, onSelect, onClose }: LabelPickerProps): import("react/jsx-runtime").JSX.Element | null;
export {};
