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
import { useUpload, Approach, Step } from './useUpload'
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
// Step labels (indexed by position within each flow)
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

const STEP_BY_STEP_TITLES: Record<number, string> = {
    [Step.UploadImages]: 'Upload Scan Images',
    [Step.UploadMasks]: 'Upload Masks',
    [Step.UploadCSVs]: 'Upload CSV Labels',
    [Step.Review]: 'Review & Validate',
    [Step.Complete]: 'Upload Complete',
}

const CSV_FILE_LIST_TITLES: Record<number, string> = {
    [Step.UploadFileList]: 'Upload File List',
    [Step.Review]: 'Review & Validate',
    [Step.Complete]: 'Upload Complete',
}

function getStepTitle(approach: Approach, step: Step): string {
    if (approach === Approach.StepByStep) {
        return STEP_BY_STEP_TITLES[step] ?? 'Upload'
    }
    return CSV_FILE_LIST_TITLES[step] ?? 'Upload'
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
        currentFlow,
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
            let response: { paths: ReviewRow[] }

            if (approach === Approach.CsvFileList) {
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

    const loadReviewDataRef = useRef(loadReviewData)
    useEffect(() => { loadReviewDataRef.current = loadReviewData }, [loadReviewData])

    useEffect(() => {
        if (currentStep === Step.Review) loadReviewDataRef.current()
    }, [currentStep])

    // ----- handleNext --------------------------------------------------------

    const handleNext = useCallback(async () => {
        if (!session) { nextStep(); return }
        try {
            setIsUploading(true)
            if (approach === Approach.StepByStep && !isFolderByType['image'] && currentStep === Step.UploadImages && images.current.length > 0) {
                const res = await uploadImages({
                    path: { project_id: projectId, session_id: session },
                    body: { files: images.current },
                })
                if (!res.data) throw new Error('Image upload failed')
            }
            if (approach === Approach.StepByStep && !isFolderByType['mask'] && currentStep === Step.UploadMasks && includeMasks && masks.current.length > 0) {
                const res = await uploadMasks({
                    path: { project_id: projectId, session_id: session },
                    body: { files: masks.current },
                })
                if (!res.data) throw new Error('Mask upload failed')
            }
            if (approach === Approach.StepByStep && !isFolderByType['csv'] && currentStep === Step.UploadCSVs && includeCSV && csvLabels.current.length > 0) {
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
            nextStep()
            toast.success('Upload processing started successfully.')
        } catch (err) {
            console.error('Process failed:', err)
            toast.error('Failed to start processing. Please try again.')
        } finally {
            setIsProcessing(false)
        }
    }, [session, reviewData, projectId, nextStep])

    // ----- Derived UI values -------------------------------------------------

    const flowLabels = approach === null
        ? ['Upload Method']
        : approach === Approach.CsvFileList
            ? CSV_FILE_LIST_LABELS
            : STEP_BY_STEP_LABELS

    const flowIndex = approach ? currentFlow.indexOf(currentStep) : 0
    const isLastStep = flowIndex === currentFlow.length - 1
    const isReviewStep = currentStep === Step.Review

    /** True when the current step is the last upload step (before review). */
    const isLastUploadStep = isReviewStep && flowIndex === currentFlow.length - 2

    /** Whether the Next / Review button should be enabled. */
    const canProceed = useMemo(() => {
        // Step 0: enabled once approach is selected
        if (currentStep === Step.ApproachSelection) return approach !== null

        if (approach === Approach.StepByStep) {
            if (currentStep === Step.UploadImages) {
                return isFolderByType['image']
                    ? pathsByType['image'].trim().length > 0
                    : uploadedFileCounts['image'] > 0
            }
            if (currentStep === Step.UploadMasks) {
                if (!includeMasks) return true
                return isFolderByType['mask']
                    ? pathsByType['mask'].trim().length > 0
                    : uploadedFileCounts['mask'] > 0
            }
            if (currentStep === Step.UploadCSVs) {
                if (!includeCSV) return true
                return isFolderByType['csv']
                    ? pathsByType['csv'].trim().length > 0
                    : uploadedFileCounts['csv'] > 0
            }
        }
        if (approach === Approach.CsvFileList) {
            if (currentStep === Step.UploadFileList) {
                return csvFile.current !== null
            }
        }
        return true
    }, [
        approach,
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
        <Modal show onHide={onClose} size="lg">
            <Modal.Header closeButton>
                <Modal.Title>{approach ? getStepTitle(approach, currentStep) : 'Upload Method'}</Modal.Title>
            </Modal.Header>

            <Modal.Body>
                <UploadStepIndicator steps={flowLabels} currentStep={flowIndex} />

                {/* Step 0: choose approach */}
                {currentStep === Step.ApproachSelection && (
                    <StepApproachSelection onSelect={setApproach} />
                )}

                {/* Step 1: scan images */}
                {approach === Approach.StepByStep && currentStep === Step.UploadImages && (
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
                {approach === Approach.StepByStep && currentStep === Step.UploadMasks && (
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
                {approach === Approach.StepByStep && currentStep === Step.UploadCSVs && (
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
                {approach === Approach.CsvFileList && currentStep === Step.UploadFileList && (
                    <StepUploadFileList
                        file={csvFile.current}
                        onFile={setCsvFile}
                    />
                )}

                {/* Step 5: review */}
                {currentStep === Step.Review && (
                    <StepReview
                        approach={approach}
                        reviewData={reviewData}
                        isLoading={isReviewLoading}
                    />
                )}

                {/* Step 6: complete */}
                {currentStep === Step.Complete && <StepComplete />}
            </Modal.Body>

            {currentFlow.length > 0 && (
                <Modal.Footer>
                    {/* Steps before Review: back + next/review */}
                    {flowIndex < currentFlow.length - 2 && (
                        <>
                            {flowIndex > 0 && (
                                <Button variant="secondary" onClick={() => prevStep()}>
                                    Back
                                </Button>
                            )}
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

                    {/* Review: process + back */}
                    {isReviewStep && (
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

                    {/* Complete: close */}
                    {currentStep === Step.Complete && (
                        <Button variant="primary" onClick={onClose}>
                            Close
                        </Button>
                    )}
                </Modal.Footer>
            )}
        </Modal>
    )
}
