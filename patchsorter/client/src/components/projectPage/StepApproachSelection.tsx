import { Form } from 'react-bootstrap'
import { Approach } from './useUpload'

interface StepApproachSelectionProps {
    onSelect: (approach: Approach) => void
}

export default function StepApproachSelection({ onSelect }: StepApproachSelectionProps) {
    return (
        <div className="d-flex flex-column gap-2">
            <label className="approach-description" htmlFor="approach-step-by-step">
                <Form.Check
                    type="radio"
                    id="approach-step-by-step"
                    name="upload-approach"
                    onChange={() => onSelect(Approach.StepByStep)}
                    label={
                        <span>
                            <strong>Step-by-Step</strong>
                            <p className="mb-0 mt-1 text-muted" style={{ fontSize: '0.9rem' }}>
                                Upload scan images, masks, and patch CSV (patch_uuid, gt_label, centroid_x, centroid_y) individually, each in a separate step.
                            </p>
                        </span>
                    }
                />
            </label>
            <label className="approach-description" htmlFor="approach-csv-file-list">
                <Form.Check
                    type="radio"
                    id="approach-csv-file-list"
                    name="upload-approach"
                    onChange={() => onSelect(Approach.CsvFileList)}
                    label={
                        <span>
                            <strong>CSV File List</strong>
                            <p className="mb-0 mt-1 text-muted" style={{ fontSize: '0.9rem' }}>
                                Upload a single CSV with header row <code>image,mask,patch_csv</code> — each row contains absolute
                                paths to files on the server. The patch_csv column references CSV files with columns: patch_uuid (optional), gt_label (optional), centroid_x (optional), centroid_y (optional).
                            </p>
                        </span>
                    }
                />
            </label>
        </div>
    )
}
