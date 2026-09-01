import { useState, useEffect, useCallback, useMemo, useRef, type ReactNode } from 'react'
import { Modal, Button } from 'react-bootstrap'
import { toast } from 'react-toastify'
import {
    uploadImages,
    uploadMasks,
    uploadPatchCsv,
    validateUpload,
    validateUploadImageCsv,
    processUpload,
    type ReviewRow,
} from '../../api_client'
import { useUpload, Approach, Step } from './useUpload'
import UploadStepIndicator from './UploadStepIndicator'
import StepApproachSelection from './StepApproachSelection'
import StepUploadImages from './StepUploadImages'
import StepUploadMasks from './StepUploadMasks'
import StepUploadPatchCsv from './StepUploadPatchCsv'
import StepUploadFileList from './StepUploadFileList'
import StepReview from './StepReview'
import StepComplete from './StepComplete'
import StepDescription from './StepDescription'
import TaskChildrenGrid from './TaskChildrenGrid'
import './UploadWizardModal.css'

// ---------------------------------------------------------------------------
// Step labels (indexed by position within each flow)
// ---------------------------------------------------------------------------

const STEP_BY_STEP_LABELS = [
    'Upload Method',
    'Upload Scan Images',
    'Upload Masks',
    'Upload Patch CSV',
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
    [Step.UploadPatchCsv]: 'Upload Patch CSV',
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

const DOCS_ACCEPTED_FORMATS = 'https://patchsorter.readthedocs.io/en/latest/accepted_formats.html'

const STEP_DESCRIPTIONS: Record<number, ReactNode> = {
    [Step.ApproachSelection]: "Choose how you'd like to upload your data. If your filenames do not follow the expected naming conventions for images, masks, and patch CSVs, we recommend using the CSV File List approach.",
    [Step.UploadImages]: (
        <>
            Upload digital pathology images. All OpenSlide-compatible formats are supported. See the{' '}
            <a href={`${DOCS_ACCEPTED_FORMATS}#images`} target="_blank" rel="noopener noreferrer">
                accepted formats documentation
            </a>{' '}
            for details.
        </>
    ),
    [Step.UploadMasks]: (
        <>
            Upload mask files or provide a server directory path containing mask files. Masks must (1) match the base name of the corresponding image file, (2) be in GeoJSON format, and (3) contain Polygon geometries only. If you wish to upload patch CSVs without masks, you can skip this step. See{' '}
            <a href={`${DOCS_ACCEPTED_FORMATS}#masks`} target="_blank" rel="noopener noreferrer">
                accepted formats documentation
            </a>{' '}
            for details.
        </>
    ),
    [Step.UploadPatchCsv]: (
        <>
            Upload patch CSV files or provide a server directory path containing patch CSV files. Patch CSVs must (1) match the base name of the corresponding image file, (2) be in CSV format, and (3) contain columns "centroid_x", "centroid_y", "width", "height", with optional columns "label", "patch_uid". See{' '}
            <a href={`${DOCS_ACCEPTED_FORMATS}#patch-csv-files`} target="_blank" rel="noopener noreferrer">
                accepted formats documentation
            </a>{' '}
            for details.
        </>
    ),
    [Step.UploadFileList]: (
        <>
            Upload a CSV file with a header row <code>image,mask,patch_csv</code>. Each row should contain server paths relative to the <code>nas_read</code> mount for the scan image, and mask and/or patch_csv. Leave a column empty if not applicable. See{' '}
            <a href={`${DOCS_ACCEPTED_FORMATS}#image-csv-file`} target="_blank" rel="noopener noreferrer">
                accepted formats documentation
            </a>{' '}
            for details.
        </>
    ),
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
        includePatchCsv,
        setIncludePatchCsv,
        isFolderByType,
        pathsByType,
        uploadedFileCounts,
        currentFlow,
        images,
        masks,
        patchCsvFiles,
        csvFile,
        setApproach,
        nextStep,
        prevStep,
        prevReviewStep,
        setIsFolderForType,
        updatePath,
        addImages,
        addMasks,
        addPatchCsvs,
        setCsvFile,
    } = useUpload(projectId)

    const [reviewData, setReviewData] = useState<ReviewRow[] | null>(null)
    const [isReviewLoading, setIsReviewLoading] = useState(false)
    const [isProcessing, setIsProcessing] = useState(false)
    const [isUploading, setIsUploading] = useState(false)
    const [childTaskId, setChildTaskId] = useState<string | null>(null)
    const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set())

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
                const res = await validateUploadImageCsv({
                    path: { project_id: projectId, session_id: session },
                    body: { csv_file: csvFile.current! },
                })
                if (res.error) {
                    const detail = (res.error as any)?.detail
                    toast.error(detail ? `Validation error: ${detail}` : 'Failed to validate paths. Please check your input and try again.')
                    return
                }
                if (!res.data) throw new Error('Validate CSV failed')
                response = res.data
                if (response.error) {
                    toast.error(response.error)
                    return
                }
            } else {
                const res = await validateUpload({
                    path: { project_id: projectId, session_id: session },
                    body: {
                        image_folder: isFolderByType['image'] ? pathsByType['image'] : null,
                        mask_folder: isFolderByType['mask'] ? pathsByType['mask'] : null,
                        patch_csv_folder: isFolderByType['patch_csv'] ? pathsByType['patch_csv'] : null,
                    },
                })
                if (res.error) {
                    const detail = (res.error as any)?.detail
                    toast.error(detail ? `Validation error: ${detail}` : 'Failed to validate paths. Please check your input and try again.')
                    return
                }
                if (!res.data) throw new Error('Validate failed')
                response = res.data
            }

            setReviewData(response.paths)
        } catch (err) {
            console.error('Review validation failed:', err)
            const detail = (err as any)?.detail ?? (err as any)?.response?.data?.detail
            toast.error(detail ? `Validation error: ${detail}` : 'Failed to validate paths. Please check your input and try again.')
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
        includePatchCsv,
        images,
        masks,
        patchCsvFiles,
        csvFile,
    ])

    const loadReviewDataRef = useRef(loadReviewData)
    useEffect(() => { loadReviewDataRef.current = loadReviewData }, [loadReviewData])

    useEffect(() => {
        if (currentStep === Step.Review) loadReviewDataRef.current()
    }, [currentStep])

    // ----- handleNext --------------------------------------------------------

    const handleRowChange = useCallback(
        (index: number, updates: Partial<ReviewRow>) => {
            setReviewData(prev =>
                prev ? prev.map((row, i) => (i === index ? { ...row, ...updates } : row)) : prev
            )
        },
        [],
    )

    const handleAllBaseMagChange = useCallback(
        (value: number | null, indices: Set<number>) => {
            setReviewData(prev =>
                prev ? prev.map((row, i) =>
                    indices.has(i) ? { ...row, base_mag: value } : row
                ) : prev
            )
        },
        [],
    )

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
            if (approach === Approach.StepByStep && !isFolderByType['patch_csv'] && currentStep === Step.UploadPatchCsv && includePatchCsv && patchCsvFiles.current.length > 0) {
                const res = await uploadPatchCsv({
                    path: { project_id: projectId, session_id: session },
                    body: { files: patchCsvFiles.current },
                })
                if (!res.data) throw new Error('Patch CSV upload failed')
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
        isFolderByType, includeMasks, includePatchCsv,
        images, masks, patchCsvFiles, nextStep,
    ])

    // ----- Process -----------------------------------------------------------

    const handleProcess = useCallback(async () => {
        if (!session || !reviewData) return
        setIsProcessing(true)
        try {
            const selectedRows = reviewData.filter((_, i) => selectedIndices.has(i))
            const res = await processUpload({
                path: { project_id: projectId, session_id: session },
                body: { paths: selectedRows.map(r => ({ image: r.image, mask: r.mask, csv: r.csv, base_mag: r.base_mag ?? null })) },
            })
            if (res.error) {
                const detail = (res.error as any)?.detail
                toast.error(detail ? `Processing error: ${detail}` : 'Failed to start processing. Please try again.')
                return
            }
            if (!res.data) throw new Error('Process failed')
            if (res.data?.task_id) {
                setChildTaskId(res.data.task_id)
            }
            nextStep()
            const taskId = res.data.task_id
            toast(
                <div>
                    <div>Processing files…</div>
                    <div>
                        <TaskChildrenGrid
                            parentTaskId={taskId}
                            containerId={`toast-task-${taskId}`}
                            onCompletion={() => {
                                setChildTaskId(null)
                            }}
                        />
                    </div>
                </div>,
                { autoClose: false, closeOnClick: false, draggable: false }
            )
        } catch (err) {
            console.error('Process failed:', err)
            const detail = (err as any)?.detail ?? (err as any)?.response?.data?.detail
            toast.error(detail ? `Processing error: ${detail}` : 'Failed to start processing. Please try again.')
        } finally {
            setIsProcessing(false)
        }
    }, [session, reviewData, selectedIndices, projectId, nextStep])

    // ----- Derived UI values -------------------------------------------------

    const flowLabels = approach === null
        ? ['Upload Method']
        : approach === Approach.CsvFileList
            ? CSV_FILE_LIST_LABELS
            : STEP_BY_STEP_LABELS

    const flowIndex = approach ? currentFlow.indexOf(currentStep) : 0
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
                    ? pathsByType['image'] !== null && pathsByType['image'].trim().length > 0
                    : uploadedFileCounts['image'] > 0
            }
            if (currentStep === Step.UploadMasks) {
                if (!includeMasks) return true
                return isFolderByType['mask']
                    ? pathsByType['mask'] !== null && pathsByType['mask'].trim().length > 0
                    : uploadedFileCounts['mask'] > 0
            }
            if (currentStep === Step.UploadPatchCsv) {
                if (!includePatchCsv) return true
                return isFolderByType['patch_csv']
                    ? pathsByType['patch_csv'] !== null && pathsByType['patch_csv'].trim().length > 0
                    : uploadedFileCounts['patch_csv'] > 0
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
        includePatchCsv,
        csvFile,
    ])

    const hasErrorsInSelection = reviewData !== null && selectedIndices.size > 0 && 
        [...selectedIndices].some(i => reviewData[i]?.status === 'error')

    const canProcess =
        reviewData !== null &&
        selectedIndices.size > 0 &&
        !hasErrorsInSelection &&
        reviewData.every(r => r.base_mag != null)

    // Disable the label toggle that would leave zero label sources
    const disabledMask = !includePatchCsv
    const disabledPatchCsv = !includeMasks

    // ----- Render ------------------------------------------------------------

    return (
        <Modal show onHide={onClose} size="xl">
            <Modal.Header closeButton>
                <Modal.Title>{approach ? getStepTitle(approach, currentStep) : 'Upload Method'}</Modal.Title>
            </Modal.Header>

            <Modal.Body>
                <UploadStepIndicator steps={flowLabels} currentStep={flowIndex} />

                {/* Step 0: choose approach */}
                {currentStep === Step.ApproachSelection && (
                    <>
                        <StepDescription>{STEP_DESCRIPTIONS[currentStep]}</StepDescription>
                        <StepApproachSelection onSelect={setApproach} />
                    </>
                )}

                {/* Step 1: scan images */}
                {approach === Approach.StepByStep && currentStep === Step.UploadImages && (
                    <>
                        <StepDescription>{STEP_DESCRIPTIONS[currentStep]}</StepDescription>
                        <StepUploadImages
                            files={images.current}
                            onAddFiles={addImages}
                            isFolder={isFolderByType['image']}
                            onToggleFolder={v => setIsFolderForType('image', v)}
                            serverPath={pathsByType['image']}
                            onServerPathChange={p => updatePath('image', p)}
                        />
                    </>
                )}

                {/* Step 2: masks */}
                {approach === Approach.StepByStep && currentStep === Step.UploadMasks && (
                    <>
                        <StepDescription>{STEP_DESCRIPTIONS[currentStep]}</StepDescription>
                        <StepUploadMasks
                            files={masks.current}
                            onAddFiles={addMasks}
                            isFolder={isFolderByType['mask']}
                            onToggleFolder={v => setIsFolderForType('mask', v)}
                            serverPath={pathsByType['mask']}
                            onServerPathChange={p => updatePath('mask', p)}
                            includeMasks={includeMasks}
                            onToggleInclude={setIncludeMasks}
                            disabled={disabledMask}
                        />
                    </>
                )}

                {/* Step 3: Patch CSV */}
                {approach === Approach.StepByStep && currentStep === Step.UploadPatchCsv && (
                    <>
                        <StepDescription>{STEP_DESCRIPTIONS[currentStep]}</StepDescription>
                        <StepUploadPatchCsv
                            files={patchCsvFiles.current}
                            onAddFiles={addPatchCsvs}
                            isFolder={isFolderByType['patch_csv']}
                            onToggleFolder={v => setIsFolderForType('patch_csv', v)}
                            serverPath={pathsByType['patch_csv']}
                            onServerPathChange={p => updatePath('patch_csv', p)}
                            includePatchCsv={includePatchCsv}
                            onToggleInclude={setIncludePatchCsv}
                            disabled={disabledPatchCsv}
                        />
                    </>
                )}

                {/* Step 4: CSV file list */}
                {approach === Approach.CsvFileList && currentStep === Step.UploadFileList && (
                    <>
                        <StepDescription>{STEP_DESCRIPTIONS[currentStep]}</StepDescription>
                        <StepUploadFileList
                            file={csvFile.current}
                            onFile={setCsvFile}
                        />
                    </>
                )}

                {/* Step 5: review */}
                {currentStep === Step.Review && (
                    <StepReview
                        approach={approach}
                        reviewData={reviewData}
                        isLoading={isReviewLoading}
                        onRowChange={handleRowChange}
                        allHaveBaseMag={reviewData !== null && reviewData.length > 0 && reviewData.every(r => r.base_mag != null)}
                        onAllBaseMagChange={handleAllBaseMagChange}
                        selectedIndices={selectedIndices}
                        onSelectionChange={setSelectedIndices}
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
                                    `Process ${selectedIndices.size} row${selectedIndices.size !== 1 ? 's' : ''}`
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
