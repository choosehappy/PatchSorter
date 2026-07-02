import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import {
    uploadImages,
    uploadMasks,
    uploadLabels,
    validateUploadPaths,
    validateUploadFolders,
    validateUploadCsv,
    processUpload,
    type ReviewRow,
} from '../../api_client'
import { useUpload } from './useUpload'
import UploadStepIndicator from './UploadStepIndicator'
import StepApproachSelection from './StepApproachSelection'
import StepUploadImages from './StepUploadImages'
import StepUploadMasks from './StepUploadMasks'
import StepUploadCSVs from './StepUploadCSVs'
import StepUploadFileList from './StepUploadFileList'
import StepReview from './StepReview'
import StepComplete from './StepComplete'
import './UploadWizardModal.css'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEP_BY_STEP_LABELS = [
    'Upload Method',
    'Upload Scan Images',
    'Upload Masks',
    'Upload CSV Labels',
    'Review Data',
    'Upload Complete',
]

const CSV_FILE_LIST_LABELS = [
    'Upload Method',
    'Upload File List',
    'Review Data',
    'Upload Complete',
]

const STEP_TITLES: Record<number, string> = {
    0: 'Upload Method',
    1: 'Upload Scan Images',
    2: 'Upload Masks',
    3: 'Upload CSV Labels',
    4: 'Upload File List',
    5: 'Review & Validate',
    6: 'Upload Complete',
}

/** Map global currentStep → position within the approach-specific label array. */
function getIndicatorStep(
    step: number,
    approach: 'stepByStep' | 'csvFileList' | null,
): number {
    if (approach === 'csvFileList') {
        const map: Record<number, number> = { 0: 0, 4: 1, 5: 2, 6: 3 }
        return map[step] ?? 0
    }
    const map: Record<number, number> = { 0: 0, 1: 1, 2: 2, 3: 3, 5: 4, 6: 5 }
    return map[step] ?? 0
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UploadWizardModalProps {
    projectId: number
    onClose: () => void
    onSessionOpen?: (session: string) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UploadWizardModal({
    projectId,
    onClose,
    onSessionOpen,
}: UploadWizardModalProps) {
    const {
        approach,
        currentStep,
        session,
        includeMasks,
        setIncludeMasks,
        includeCSV,
        setIncludeCSV,
        isFolderByType,
        pathsByType,
        uploadedFileCounts,
        images,
        masks,
        csvLabels,
        csvFile,
        setApproach,
        nextStep,
        prevStep,
        prevReviewStep,
        setIsFolderForType,
        updatePath,
        addImages,
        addMasks,
        addCSVLabels,
        setCsvFile,
    } = useUpload(projectId)

    const [reviewData, setReviewData] = useState<ReviewRow[] | null>(null)
    const [isReviewLoading, setIsReviewLoading] = useState(false)
    const [isProcessing, setIsProcessing] = useState(false)
    const [isUploading, setIsUploading] = useState(false)

    // Notify parent when session is created
    useEffect(() => {
        if (session && onSessionOpen) onSessionOpen(session)
    }, [session, onSessionOpen])

    // ----- Review validation -------------------------------------------------

    const loadReviewData = useCallback(async () => {
        if (!session) return
        setIsReviewLoading(true)
        setReviewData(null)
        try {
            // TODO: replace with generated SDK functions after backend is implemented
            let response: { paths: ReviewRow[] }

            if (approach === 'csvFileList') {
                const res = await validateUploadCsv({
                    path: { project_id: projectId, session_id: session },
                    body: { csv_file: csvFile.current! },
                })
                if (!res.data) throw new Error('Validate CSV failed')
                response = res.data
            } else if (Object.values(isFolderByType).some(Boolean)) {
                const res = await validateUploadFolders({
                    path: { project_id: projectId, session_id: session },
                    body: {
                        image_folder: pathsByType['image'],
                        mask_folder: pathsByType['mask'],
                        label_folder: pathsByType['csv'],
                    },
                })
                if (!res.data) throw new Error('Validate folders failed')
                response = res.data
            } else {
                const paths = [
                    ...images.current.map(f => ({ type: 'image' as const, filename: f.name })),
                    ...(includeMasks
                        ? masks.current.map(f => ({ type: 'mask' as const, filename: f.name }))
                        : []),
                    ...(includeCSV
                        ? csvLabels.current.map(f => ({ type: 'csv' as const, filename: f.name }))
                        : []),
                ]
                const res = await validateUploadPaths({
                    path: { project_id: projectId, session_id: session },
                    body: { paths },
                })
                if (!res.data) throw new Error('Validate paths failed')
                response = res.data
            }

            setReviewData(response.paths)
        } catch (err) {
            console.error('Review validation failed:', err)
            toast.error('Failed to validate paths. Please check your input and try again.')
        } finally {
            setIsReviewLoading(false)
        }
    }, [
        session,
        approach,
        projectId,
        isFolderByType,
        pathsByType,
        includeMasks,
        includeCSV,
        images,
        masks,
        csvLabels,
        csvFile,
    ])

    // Use a ref to avoid stale closure in the effect below
    const loadReviewDataRef = useRef(loadReviewData)
    useEffect(() => { loadReviewDataRef.current = loadReviewData }, [loadReviewData])

    // Trigger validation automatically when the user reaches the review step
    useEffect(() => {
        if (currentStep === 5) loadReviewDataRef.current()
    }, [currentStep])

    // ----- handleNext (uploads files then advances step) -------------------

    const handleNext = useCallback(async () => {
        if (!session) { nextStep(); return }
        // For drag-and-drop upload steps, send files to the server before advancing
        try {
            setIsUploading(true)
            if (approach === 'stepByStep' && !isFolderByType['image'] && currentStep === 1 && images.current.length > 0) {
                const res = await uploadImages({
                    path: { project_id: projectId, session_id: session },
                    body: { files: images.current },
                })
                if (!res.data) throw new Error('Image upload failed')
            }
            if (approach === 'stepByStep' && !isFolderByType['mask'] && currentStep === 2 && includeMasks && masks.current.length > 0) {
                const res = await uploadMasks({
                    path: { project_id: projectId, session_id: session },
                    body: { files: masks.current },
                })
                if (!res.data) throw new Error('Mask upload failed')
            }
            if (approach === 'stepByStep' && !isFolderByType['csv'] && currentStep === 3 && includeCSV && csvLabels.current.length > 0) {
                const res = await uploadLabels({
                    path: { project_id: projectId, session_id: session },
                    body: { files: csvLabels.current },
                })
                if (!res.data) throw new Error('Label upload failed')
            }
        } catch (err) {
            console.error('File upload failed:', err)
            toast.error('Failed to upload files to server. Please try again.')
            return
        } finally {
            setIsUploading(false)
        }
        nextStep()
    }, [
        session, approach, currentStep, projectId,
        isFolderByType, includeMasks, includeCSV,
        images, masks, csvLabels, nextStep,
    ])

    // ----- Process -----------------------------------------------------------

    const handleProcess = useCallback(async () => {
        if (!session || !reviewData) return
        setIsProcessing(true)
        try {
            const res = await processUpload({
                path: { project_id: projectId, session_id: session },
                body: { paths: reviewData },
            })
            if (!res.data) throw new Error('Process failed')
            nextStep()  // advance to step 6 (Complete)
            toast.success('Upload processing started successfully.')
        } catch (err) {
            console.error('Process failed:', err)
            toast.error('Failed to start processing. Please try again.')
        } finally {
            setIsProcessing(false)
        }
    }, [session, reviewData, projectId, nextStep])

    // ----- Derived UI values -------------------------------------------------

    const steps = approach === 'csvFileList' ? CSV_FILE_LIST_LABELS : STEP_BY_STEP_LABELS
    const indicatorStep = getIndicatorStep(currentStep, approach)

    /** True when the next click leads to step 5 (Review). */
    const isLastUploadStep = useMemo(() => {
        if (approach === 'csvFileList') return currentStep === 4
        if (includeCSV) return currentStep === 3
        if (includeMasks) return currentStep === 2
        return currentStep === 1
    }, [approach, currentStep, includeMasks, includeCSV])

    /** Whether the Next / Review button should be enabled. */
    const canProceed = useMemo(() => {
        if (currentStep === 1) {
            return isFolderByType['image']
                ? pathsByType['image'].trim().length > 0
                : uploadedFileCounts['image'] > 0
        }
        if (currentStep === 2) {
            if (!includeMasks) return true
            return isFolderByType['mask']
                ? pathsByType['mask'].trim().length > 0
                : uploadedFileCounts['mask'] > 0
        }
        if (currentStep === 3) {
            if (!includeCSV) return true
            return isFolderByType['csv']
                ? pathsByType['csv'].trim().length > 0
                : uploadedFileCounts['csv'] > 0
        }
        if (currentStep === 4) {
            return csvFile.current !== null
        }
        return true
    }, [
        currentStep,
        isFolderByType,
        pathsByType,
        uploadedFileCounts,
        includeMasks,
        includeCSV,
        csvFile,
    ])

    const canProcess =
        reviewData !== null &&
        reviewData.length > 0 &&
        reviewData.some(r => r.status === 'ok')

    // ----- Render ------------------------------------------------------------

    return (
        <Modal show onHide={onClose} size="lg" centered>
            <Modal.Header closeButton>
                <Modal.Title>{STEP_TITLES[currentStep] ?? 'Upload'}</Modal.Title>
            </Modal.Header>

            <Modal.Body>
                <UploadStepIndicator steps={steps} currentStep={indicatorStep} />

                {/* Step 0: choose approach */}
                {currentStep === 0 && (
                    <StepApproachSelection onSelect={setApproach} />
                )}

                {/* Step 1: scan images */}
                {approach === 'stepByStep' && currentStep === 1 && (
                    <StepUploadImages
                        files={images.current}
                        onAddFiles={addImages}
                        isFolder={isFolderByType['image']}
                        onToggleFolder={v => setIsFolderForType('image', v)}
                        serverPath={pathsByType['image']}
                        onServerPathChange={p => updatePath('image', p)}
                    />
                )}

                {/* Step 2: masks */}
                {approach === 'stepByStep' && currentStep === 2 && (
                    <StepUploadMasks
                        files={masks.current}
                        onAddFiles={addMasks}
                        isFolder={isFolderByType['mask']}
                        onToggleFolder={v => setIsFolderForType('mask', v)}
                        serverPath={pathsByType['mask']}
                        onServerPathChange={p => updatePath('mask', p)}
                        includeMasks={includeMasks}
                        onToggleInclude={setIncludeMasks}
                    />
                )}

                {/* Step 3: CSV labels */}
                {approach === 'stepByStep' && currentStep === 3 && (
                    <StepUploadCSVs
                        files={csvLabels.current}
                        onAddFiles={addCSVLabels}
                        isFolder={isFolderByType['csv']}
                        onToggleFolder={v => setIsFolderForType('csv', v)}
                        serverPath={pathsByType['csv']}
                        onServerPathChange={p => updatePath('csv', p)}
                        includeCSV={includeCSV}
                        onToggleInclude={setIncludeCSV}
                    />
                )}

                {/* Step 4: CSV file list */}
                {approach === 'csvFileList' && currentStep === 4 && (
                    <StepUploadFileList
                        file={csvFile.current}
                        onFile={setCsvFile}
                    />
                )}

                {/* Step 5: review */}
                {currentStep === 5 && (
                    <StepReview
                        approach={approach}
                        reviewData={reviewData}
                        isLoading={isReviewLoading}
                    />
                )}

                {/* Step 6: complete */}
                {currentStep === 6 && <StepComplete />}
            </Modal.Body>

            {currentStep > 0 && (
                <Modal.Footer>
                    {/* Steps 1–4: back + next/review */}
                    {currentStep > 0 && currentStep < 5 && (
                        <>
                            <Button variant="secondary" onClick={() => prevStep()}>
                                Back
                            </Button>
                            <Button
                                variant="primary"
                                onClick={handleNext}
                                disabled={!canProceed || isUploading}
                            >
                                {isUploading ? (
                                    <>
                                        <span
                                            className="spinner-border spinner-border-sm me-2"
                                            role="status"
                                            aria-hidden="true"
                                        />
                                        Uploading…
                                    </>
                                ) : isLastUploadStep ? 'Review & Validate' : 'Next'}
                            </Button>
                        </>
                    )}

                    {/* Step 5: review — process + back */}
                    {currentStep === 5 && (
                        <>
                            <Button
                                variant="secondary"
                                onClick={prevReviewStep}
                                disabled={isProcessing}
                            >
                                Back
                            </Button>
                            <Button
                                variant="primary"
                                onClick={handleProcess}
                                disabled={isProcessing || !canProcess || isReviewLoading}
                            >
                                {isProcessing ? (
                                    <>
                                        <span
                                            className="spinner-border spinner-border-sm me-2"
                                            role="status"
                                            aria-hidden="true"
                                        />
                                        Processing…
                                    </>
                                ) : (
                                    'Process'
                                )}
                            </Button>
                        </>
                    )}

                    {/* Step 6: complete — close */}
                    {currentStep === 6 && (
                        <Button variant="primary" onClick={onClose}>
                            Close
                        </Button>
                    )}
                </Modal.Footer>
            )}
        </Modal>
    )
}
