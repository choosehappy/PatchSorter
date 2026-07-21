import { useState } from 'react'
import { Form } from 'react-bootstrap'
import { ACCEPT_ATTR, ACCEPTED_EXTS } from '../../constants'

interface StepUploadImagesProps {
    files: File[]
    onAddFiles: (files: File[]) => void
    isFolder: boolean
    onToggleFolder: (isFolder: boolean) => void
    serverPath: string | null
    onServerPathChange: (path: string) => void
}

export default function StepUploadImages({
    files,
    onAddFiles,
    isFolder,
    onToggleFolder,
    serverPath,
    onServerPathChange,
}: StepUploadImagesProps) {
    const [dragOver, setDragOver] = useState(false)

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        const dropped = Array.from(e.dataTransfer.files).filter(f => ACCEPTED_EXTS.test(f.name))
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
                            <div className="mb-2" style={{ fontSize: '2rem' }}>🖼️</div>
                            <div>Drag &amp; drop scan images here, or <strong>click to browse</strong></div>
                            <div className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>
                                Accepts: .tif, .tiff, .png, .jpg, .jpeg
                            </div>
                        </div>
                        <input
                            type="file"
                            multiple
                            accept={ACCEPT_ATTR}
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
                    <Form.Label>Server directory path for scan images</Form.Label>
                    <Form.Control
                        type="text"
                        placeholder="relative/path/to/images/"
                        value={serverPath ?? ''}
                        onChange={e => onServerPathChange(e.target.value)}
                    />
                    <Form.Text className="text-muted">
                        Relative path to a directory on the server. All matching image files inside
                        will be imported.
                    </Form.Text>
                </Form.Group>
            )}
        </div>
    )
}
