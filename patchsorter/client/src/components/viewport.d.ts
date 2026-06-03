import { type WorldInfo } from '../api_client';
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
    worldInfo: WorldInfo | null;
    refreshTick: number;
    onBoundsChange: (bounds: MapBounds) => void;
    onZoomChange: (osmZoom: number, level: number) => void;
}
export default function Viewport({ projectId, colorBy, filterBy, selectedCells, numClasses, worldInfo, refreshTick, onBoundsChange, onZoomChange, }: ViewportProps): import("react/jsx-runtime").JSX.Element;
export {};
