export interface ConfusionData {
    gt_labels: number[]
    pred_labels: number[]
    matrix: number[][]
}

interface ConfusionMatrixProps {
    confusionData: ConfusionData | null
    selectedCells: Set<string>
    colorBy: string
    classLabels: string[]
    classColors: string[]
    classIds: number[]
    onCellClick: (gt: number, pred: number, multiSelect: boolean) => void
    onHeaderClick: (axis: 'gt' | 'pred', index: number, multiSelect: boolean) => void
}

export default function ConfusionMatrix({
    confusionData,
    selectedCells,
    colorBy,
    classLabels,
    classColors,
    classIds,
    onCellClick,
    onHeaderClick,
}: ConfusionMatrixProps) {
    const numClasses = classLabels.length

    // Pre-compute matrix values from confusionData
    const { cellValues, rowTotals, colTotals, grandTotal } = computeValues(
        confusionData, numClasses, classIds
    )

    function formatPct(val: number, total: number): string {
        if (total === 0 || val === 0) return ''
        const pct = val / total * 100
        return pct >= 0.1 ? pct.toFixed(1) + '%' : '<0.1%'
    }

    function cellBg(val: number, total: number): string {
        if (total === 0 || val === 0) return '#fff'
        const intensity = Math.min(1, Math.log1p(val) / Math.log1p(total))
        return `rgba(100, 100, 200, ${(intensity * 0.3).toFixed(3)})`
    }

    return (
        <div className="matrix-container">
            <div className="gt-axis-label">Ground Truth Labels</div>
            <div style={{ display: 'flex' }}>
                <div className="axis-label">Prediction Labels</div>
                <table className="matrix-table">
                    <tbody>
                        {/* Header row */}
                        <tr>
                            <th className="corner-cell" />
                            {classLabels.map((label, gt) => (
                                <th
                                    key={gt}
                                    className="gt-header"
                                    style={{ backgroundColor: classColors[gt] }}
                                    onClick={e => onHeaderClick('gt', gt, e.ctrlKey || e.metaKey)}
                                >
                                    {label}
                                </th>
                            ))}
                            <th
                                className="totals-header gt-header"
                                style={{ background: '#e0e0e0', color: '#333' }}
                            >
                                Totals
                            </th>
                        </tr>

                        {/* Data rows */}
                        {classLabels.map((label, pred) => {
                            if (label === 'unassigned') return null
                            return (
                            <tr key={pred}>
                                <th
                                    className="pred-header"
                                    style={{ backgroundColor: classColors[pred] }}
                                    onClick={e => onHeaderClick('pred', pred, e.ctrlKey || e.metaKey)}
                                >
                                    {label}
                                </th>
                                {classLabels.map((_, gt) => {
                                    const key = `${gt},${pred}`
                                    const isSelected = selectedCells.has(key)
                                    const val = cellValues[pred][gt]
                                    return (
                                        <td
                                            key={gt}
                                            className={`cell${isSelected ? ' selected' : ''}`}
                                            style={{
                                                borderColor: isSelected
                                                    ? (colorBy === 'gt' ? classColors[gt] : classColors[pred])
                                                    : '#f8f8f8',
                                                backgroundColor: cellBg(val, grandTotal),
                                            }}
                                            onClick={e => onCellClick(gt, pred, e.ctrlKey || e.metaKey)}
                                        >
                                            {formatPct(val, grandTotal)}
                                        </td>
                                    )
                                })}
                                <td className="totals-cell">
                                    {formatPct(rowTotals[pred], grandTotal)}
                                </td>
                            </tr>
                            )
                        })}

                        {/* Totals row */}
                        <tr>
                            <th className="totals-header">Totals</th>
                            {classLabels.map((_, gt) => (
                                <td key={gt} className="totals-cell">
                                    {formatPct(colTotals[gt], grandTotal)}
                                </td>
                            ))}
                            <td className="totals-cell" style={{ fontWeight: 'bold' }}>
                                {grandTotal > 0 ? grandTotal.toLocaleString() : ''}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    )
}

function computeValues(
    confusionData: ConfusionData | null,
    numClasses: number,
    classIds: number[]
): {
    cellValues: number[][]
    rowTotals: number[]
    colTotals: number[]
    grandTotal: number
} {
    const cellValues = Array.from({ length: numClasses }, () => new Array(numClasses).fill(0))
    const rowTotals = new Array(numClasses).fill(0)
    const colTotals = new Array(numClasses).fill(0)
    let grandTotal = 0

    if (!confusionData) return { cellValues, rowTotals, colTotals, grandTotal }

    const { gt_labels, pred_labels, matrix } = confusionData
    const gtIndexMap: Record<number, number> = {}
    gt_labels.forEach((label, idx) => { gtIndexMap[label] = idx })
    const predIndexMap: Record<number, number> = {}
    pred_labels.forEach((label, idx) => { predIndexMap[label] = idx })

    for (let gt = 0; gt < numClasses; gt++) {
        for (let pred = 0; pred < numClasses; pred++) {
            const gtIdx = gtIndexMap[classIds[gt]]
            const predIdx = predIndexMap[classIds[pred]]
            const val = (gtIdx !== undefined && predIdx !== undefined)
                ? matrix[gtIdx][predIdx]
                : 0
            cellValues[pred][gt] = val
            rowTotals[pred] += val
            colTotals[gt] += val
            grandTotal += val
        }
    }

    return { cellValues, rowTotals, colTotals, grandTotal }
}
