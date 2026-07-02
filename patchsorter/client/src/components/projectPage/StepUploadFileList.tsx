import { useState, useEffect } from 'react'
import { Table, Alert } from 'react-bootstrap'

interface StepUploadFileListProps {
    file: File | null
    onFile: (file: File | null) => void
}

interface CSVParseResult {
    valid: boolean
    rowCount: number
    previewRows: string[][]
    error?: string
}

function parseFileListCSV(text: string): CSVParseResult {
    const lines = text.split(/\r?\n/).filter(l => l.trim().length > 0)
    if (lines.length === 0) {
        return { valid: false, rowCount: 0, previewRows: [], error: 'CSV file is empty.' }
    }
    const headerCols = lines[0].split(',').map(h => h.trim().toLowerCase())
    if (headerCols.length < 3 || headerCols[0] !== 'image' || headerCols[1] !== 'mask' || headerCols[2] !== 'label') {
        return {
            valid: false,
            rowCount: 0,
            previewRows: [],
            error: `Invalid header. Expected "image,mask,label" but found "${lines[0]}".`,
        }
    }
    const dataLines = lines.slice(1)
    const previewRows = dataLines.slice(0, 5).map(l => l.split(',').map(v => v.trim()))
    return { valid: true, rowCount: dataLines.length, previewRows }
}

export default function StepUploadFileList({ file, onFile }: StepUploadFileListProps) {
    const [dragOver, setDragOver] = useState(false)
    const [parseResult, setParseResult] = useState<CSVParseResult | null>(null)

    // Parse CSV whenever the file changes
    useEffect(() => {
        if (!file) {
            setParseResult(null)
            return
        }
        const reader = new FileReader()
        reader.onload = e => {
            const text = e.target?.result as string
            setParseResult(parseFileListCSV(text))
        }
        reader.readAsText(file)
    }, [file])

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        const dropped = Array.from(e.dataTransfer.files).find(f => /\.csv$/i.test(f.name))
        if (dropped) onFile(dropped)
        setDragOver(false)
    }

    const handleBrowse = (e: React.ChangeEvent<HTMLInputElement>) => {
        const picked = e.target.files?.[0]
        if (picked) onFile(picked)
        e.target.value = ''
    }

    const handleClear = () => {
        onFile(null)
        setParseResult(null)
    }

    return (
        <div>
            <p className="text-muted mb-3" style={{ fontSize: '0.9rem' }}>
                Upload a CSV file with a header row <code>image,mask,label</code>. Each subsequent row should
                contain absolute server paths for the scan image, mask file (optional), and label CSV
                (optional). Leave a column empty if not applicable.
            </p>

            {!file ? (
                <label
                    className={`upload-dropzone${dragOver ? ' drag-over' : ''}`}
                    onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                >
                    <div>
                        <div className="mb-2" style={{ fontSize: '2rem' }}>📄</div>
                        <div>Drag &amp; drop a CSV file here, or <strong>click to browse</strong></div>
                        <div className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>Accepts: .csv only</div>
                    </div>
                    <input
                        type="file"
                        accept=".csv"
                        style={{ display: 'none' }}
                        onChange={handleBrowse}
                    />
                </label>
            ) : (
                <div>
                    <div className="d-flex align-items-center justify-content-between mb-2">
                        <span>
                            <strong>{file.name}</strong>
                            <span className="text-muted ms-2" style={{ fontSize: '0.85rem' }}>
                                ({(file.size / 1024).toFixed(1)} KB)
                            </span>
                        </span>
                        <button
                            type="button"
                            className="btn btn-sm btn-outline-secondary"
                            onClick={handleClear}
                        >
                            Remove
                        </button>
                    </div>

                    {parseResult && !parseResult.valid && (
                        <Alert variant="danger" className="py-2">
                            {parseResult.error}
                        </Alert>
                    )}

                    {parseResult?.valid && (
                        <div>
                            <small className="text-muted">
                                {parseResult.rowCount} row{parseResult.rowCount !== 1 ? 's' : ''} found.
                                {parseResult.rowCount > 5 && ' Showing first 5:'}
                            </small>
                            <div style={{ overflowX: 'auto', marginTop: 6 }}>
                                <Table bordered size="sm" style={{ fontSize: '0.8rem', marginBottom: 0 }}>
                                    <thead className="table-light">
                                        <tr>
                                            <th>image</th>
                                            <th>mask</th>
                                            <th>label</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {parseResult.previewRows.map((row, i) => (
                                            <tr key={i}>
                                                <td className="text-truncate" style={{ maxWidth: 200 }}>{row[0] ?? ''}</td>
                                                <td className="text-truncate" style={{ maxWidth: 200 }}>{row[1] ?? ''}</td>
                                                <td className="text-truncate" style={{ maxWidth: 200 }}>{row[2] ?? ''}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </Table>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
