import { type WorldInfo, type PatchResponse, type LabelClassResponse } from '../api_client';
export interface MapBounds {
    left: number;
    right: number;
    top: number;
    bottom: number;
}
interface ViewportProps {
    projectId: number;
    colorBy: string;
    filterBy: string;
    selectedCells: Set<string>;
    numClasses: number;
    classIds: number[];
    worldInfo: WorldInfo | null;
    refreshTick: number;
    onBoundsChange: (bounds: MapBounds) => void;
    onZoomChange: (osmZoom: number, level: number) => void;
    onLassoComplete: (polygon: number[][], pageSize: number) => void;
    onViewportClick: () => void;
    onHoverPatch: (patch: PatchResponse | null) => void;
    pageSize: number;
    selectedPatches: PatchResponse[];
    hoveredPatch: PatchResponse | null;
    showPatches: boolean;
    labelClasses: LabelClassResponse[];
}
export default function Viewport({ projectId, colorBy, filterBy, selectedCells, numClasses, classIds, worldInfo, refreshTick, onBoundsChange, onZoomChange, onLassoComplete, onViewportClick, onHoverPatch, pageSize, selectedPatches, hoveredPatch, showPatches, labelClasses, }: ViewportProps): import("react/jsx-runtime").JSX.Element;
export {};
