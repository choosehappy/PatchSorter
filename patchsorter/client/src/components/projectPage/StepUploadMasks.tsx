import { useState } from 'react'
import { Form } from 'react-bootstrap'

interface StepUploadMasksProps {
    files: File[]
    onAddFiles: (files: File[]) => void
    isFolder: boolean
    onToggleFolder: (isFolder: boolean) => void
    serverPath: string
    onServerPathChange: (path: string) => void
    includeMasks: boolean
    onToggleInclude: (include: boolean) => void
    disabled: boolean
}

export default function StepUploadMasks({
    files,
    onAddFiles,
    isFolder,
    onToggleFolder,
    serverPath,
    onServerPathChange,
    includeMasks,
    onToggleInclude,
    disabled,
}: StepUploadMasksProps) {
    const [dragOver, setDragOver] = useState(false)

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        const dropped = Array.from(e.dataTransfer.files).filter(f => /\.geojson$/i.test(f.name))
        if (dropped.length) onAddFiles(dropped)
        setDragOver(false)
    }

    const handleBrowse = (e: React.ChangeEvent<HTMLInputElement>) => {
        const selected = Array.from(e.target.files ?? [])
        if (selected.length) onAddFiles(selected)
        e.target.value = ''
    }

    return (
        <div>
            <Form.Check
                type="switch"
                id="include-masks-toggle"
                label="Include masks"
                checked={includeMasks}
                onChange={e => onToggleInclude(e.target.checked)}
                disabled={disabled}
                className="mb-3"
            />

            {!includeMasks ? (
                <p className="text-muted fst-italic">Mask upload skipped — no masks will be associated with imported images.</p>
            ) : (
                <>
                    <div className="upload-mode-toggle">
                        <button
                            type="button"
                            className={`toggle-option${!isFolder ? ' active' : ''}`}
                            onClick={() => onToggleFolder(false)}
                        >
                            Upload Files
                        </button>
                        <button
                            type="button"
                            className={`toggle-option${isFolder ? ' active' : ''}`}
                            onClick={() => onToggleFolder(true)}
                        >
                            Load Folder
                        </button>
                    </div>

                    {!isFolder ? (
                        <>
                            <label
                                className={`upload-dropzone${dragOver ? ' drag-over' : ''}`}
                                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                                onDragLeave={() => setDragOver(false)}
                                onDrop={handleDrop}
                            >
                                <div>
                                    <div className="mb-2" style={{ fontSize: '2rem' }}>🗺️</div>
                                    <div>Drag &amp; drop GeoJSON mask files here, or <strong>click to browse</strong></div>
                                    <div className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>
                                        Accepts: .geojson only
                                    </div>
                                </div>
                                <input
                                    type="file"
                                    multiple
                                    accept=".geojson"
                                    style={{ display: 'none' }}
                                    onChange={handleBrowse}
                                />
                            </label>
                            {files.length > 0 && (
                                <div className="mt-2">
                                    <small className="text-muted">
                                        {files.length} file{files.length !== 1 ? 's' : ''} selected
                                    </small>
                                    <div style={{ maxHeight: 160, overflowY: 'auto', marginTop: 4 }}>
                                        {files.map((f, i) => (
                                            <div key={i} className="upload-file-item">
                                                <span className="file-name">{f.name}</span>
                                                <small className="text-muted flex-shrink-0">
                                                    {(f.size / 1024).toFixed(0)} KB
                                                </small>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </>
                    ) : (
                        <Form.Group>
                            <Form.Label>Server directory path for mask files</Form.Label>
                            <Form.Control
                                type="text"
                                placeholder="/absolute/path/to/masks/"
                                value={serverPath}
                                onChange={e => onServerPathChange(e.target.value)}
                            />
                            <Form.Text className="text-muted">
                                Absolute path to a directory on the server containing .geojson mask files.
                            </Form.Text>
                        </Form.Group>
                    )}
                </>
            )}
        </div>
    )
}
