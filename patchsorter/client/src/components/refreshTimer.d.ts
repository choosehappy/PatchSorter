interface RefreshTimerProps {
    intervalMs: number | null;
    onIntervalChange: (ms: number | null) => void;
    onTick: () => void;
}
export default function RefreshTimer({ intervalMs, onIntervalChange, onTick }: RefreshTimerProps): import("react/jsx-runtime").JSX.Element;
export {};
