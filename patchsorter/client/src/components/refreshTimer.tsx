import { useState, useEffect, useRef } from 'react'

const OPTIONS: { label: string; ms: number | null }[] = [
    { label: '1s', ms: 1000 },
    { label: '5s', ms: 5000 },
    { label: '10s', ms: 10000 },
    { label: '30s', ms: 30000 },
    { label: 'Off', ms: null },
]

const RADIUS = 9
const STROKE_WIDTH = 2.5
const CIRC = 2 * Math.PI * RADIUS
const SIZE = (RADIUS + STROKE_WIDTH) * 2

interface RefreshTimerProps {
    intervalMs: number | null
    onIntervalChange: (ms: number | null) => void
    onTick: () => void
}

export default function RefreshTimer({ intervalMs, onIntervalChange, onTick }: RefreshTimerProps) {
    const [progress, setProgress] = useState(1)
    const lastTickRef = useRef(Date.now())
    const onTickRef = useRef(onTick)
    onTickRef.current = onTick

    // Tick interval — fires the actual refresh
    useEffect(() => {
        if (intervalMs === null) {
            setProgress(1)
            return
        }
        lastTickRef.current = Date.now()
        setProgress(1)
        const id = setInterval(() => {
            lastTickRef.current = Date.now()
            setProgress(1)
            onTickRef.current()
        }, intervalMs)
        return () => clearInterval(id)
    }, [intervalMs])

    // Visual update loop at ~20 fps
    useEffect(() => {
        if (intervalMs === null) return
        const id = setInterval(() => {
            const elapsed = Date.now() - lastTickRef.current
            setProgress(Math.max(0, 1 - elapsed / intervalMs))
        }, 50)
        return () => clearInterval(id)
    }, [intervalMs])

    const dashoffset = CIRC * (1 - progress)

    return (
        <div className="control-group refresh-timer">
            <label>Refresh</label>
            <div className="refresh-timer-inner">
                <select
                    value={intervalMs ?? 'off'}
                    onChange={e => {
                        const v = e.target.value
                        onIntervalChange(v === 'off' ? null : Number(v))
                    }}
                >
                    {OPTIONS.map(o => (
                        <option key={o.label} value={o.ms ?? 'off'}>{o.label}</option>
                    ))}
                </select>
                {intervalMs !== null ? (
                    <svg width={SIZE} height={SIZE} className="refresh-circle">
                        <circle
                            cx={SIZE / 2} cy={SIZE / 2} r={RADIUS}
                            fill="none" stroke="#d0d0d0"
                            strokeWidth={STROKE_WIDTH}
                        />
                        <circle
                            cx={SIZE / 2} cy={SIZE / 2} r={RADIUS}
                            fill="none" stroke="#4a90d9"
                            strokeWidth={STROKE_WIDTH}
                            strokeDasharray={CIRC}
                            strokeDashoffset={dashoffset}
                            strokeLinecap="round"
                            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
                        />
                    </svg>
                ) : (
                    <svg width={SIZE} height={SIZE} className="refresh-circle">
                        <circle
                            cx={SIZE / 2} cy={SIZE / 2} r={RADIUS}
                            fill="none" stroke="#d0d0d0"
                            strokeWidth={STROKE_WIDTH}
                        />
                    </svg>
                )}
            </div>
        </div>
    )
}
