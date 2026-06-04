export interface ConfusionData {
    gt_labels: number[];
    pred_labels: number[];
    matrix: number[][];
}
interface ConfusionMatrixProps {
    confusionData: ConfusionData | null;
    selectedCells: Set<string>;
    colorBy: string;
    classLabels: string[];
    classColors: string[];
    classIds: number[];
    onCellClick: (gt: number, pred: number, multiSelect: boolean) => void;
    onHeaderClick: (axis: 'gt' | 'pred', index: number, multiSelect: boolean) => void;
}
export default function ConfusionMatrix({ confusionData, selectedCells, colorBy, classLabels, classColors, classIds, onCellClick, onHeaderClick, }: ConfusionMatrixProps): import("react/jsx-runtime").JSX.Element;
export {};
