import { useState, useRef, useCallback, useMemo } from 'react'
import { toast } from 'react-toastify'
import { openUploadSession } from '../../api_client'
export type { ReviewRow } from '../../api_client'

// ---------------------------------------------------------------------------
// Enums & flow definitions
// ---------------------------------------------------------------------------

export enum Step {
    ApproachSelection = 0,
    UploadImages = 1,
    UploadMasks = 2,
    UploadPatchCsv = 3,
    UploadFileList = 4,
    Review = 5,
    Complete = 6,
}

export const STEP_BY_STEP_FLOW = [
    Step.ApproachSelection,
    Step.UploadImages,
    Step.UploadMasks,
    Step.UploadPatchCsv,
    Step.Review,
    Step.Complete,
] as const

export const CSV_FILE_LIST_FLOW = [
    Step.ApproachSelection,
    Step.UploadFileList,
    Step.Review,
    Step.Complete,
] as const

export enum Approach {
    StepByStep = 'stepByStep',
    CsvFileList = 'csvFileList',
}

export type UploadType = 'image' | 'mask' | 'patch_csv'

// ---------------------------------------------------------------------------
// Flow helpers
// ---------------------------------------------------------------------------

function getFlow(approach: Approach): readonly Step[] {
    if (approach === Approach.StepByStep) {
        return STEP_BY_STEP_FLOW
    }
    return CSV_FILE_LIST_FLOW
}

function findIndex(flow: readonly Step[], step: Step): number {
    return flow.findIndex(s => s === step)
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface UseUploadReturn {
    approach: Approach | null
    currentStep: Step
    session: string | null
    includeMasks: boolean
    includePatchCsv: boolean
    disabledMask: boolean
    disabledPatchCsv: boolean
    isFolderByType: Record<UploadType, boolean>
    pathsByType: Record<UploadType, string>
    uploadedFileCounts: Record<UploadType, number>
    currentFlow: readonly Step[]

    // Refs
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    patchCsvFiles: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>

    // Actions
    setApproach: (a: Approach) => Promise<void>
    nextStep: () => void
    prevStep: (targetStep?: Step) => void
    prevReviewStep: () => void
    setIncludeMasks: (v: boolean) => void
    setIncludePatchCsv: (v: boolean) => void
    setIsFolderForType: (type: UploadType, value: boolean) => void
    updatePath: (type: UploadType, path: string) => void
    addImages: (files: File[]) => void
    addMasks: (files: File[]) => void
    addPatchCsvs: (files: File[]) => void
    setCsvFile: (file: File | null) => void
    reset: () => void
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useUpload(projectId: number): UseUploadReturn {
    const [approach, setApproachState] = useState<Approach | null>(null)
    const [currentStep, setCurrentStep] = useState(Step.ApproachSelection)
    const [session, setSession] = useState<string | null>(null)
    const [includeMasks, setIncludeMasksState] = useState(true)
    const [includePatchCsv, setIncludePatchCsvState] = useState(true)
    const [disabledMask, setDisabledMaskState] = useState(false)
    const [disabledPatchCsv, setDisabledPatchCsvState] = useState(false)
    const [isFolderByType, setIsFolderByType] = useState<Record<UploadType, boolean>>({
        image: false,
        mask: false,
        patch_csv: false,
    })
    const [pathsByType, setPathsByType] = useState<Record<UploadType, string>>({
        image: '',
        mask: '',
        patch_csv: '',
    })
    const [uploadedFileCounts, setUploadedFileCounts] = useState<Record<UploadType, number>>({
        image: 0,
        mask: 0,
        patch_csv: 0,
    })

    const images = useRef<File[]>([])
    const masks = useRef<File[]>([])
    const patchCsvFiles = useRef<File[]>([])
    const csvFile = useRef<File | null>(null)

    const sessionRef = useRef<string | null>(null)
    const approachRef = useRef(approach)
    approachRef.current = approach
    const includeMasksRef = useRef(includeMasks)
    includeMasksRef.current = includeMasks
    const includePatchCsvRef = useRef(includePatchCsv)
    includePatchCsvRef.current = includePatchCsv

    // Current flow (static per approach — toggles only hide components, don't alter flow)
    const currentFlow = useMemo(
        () => getFlow(approach ?? Approach.StepByStep),
        [approach],
    )

    // ----- openSession --------------------------------------------------------

    const openSession = useCallback(async () => {
        if (sessionRef.current) return
        const result = await openUploadSession({ path: { project_id: projectId } })
        if (!result.data?.session) throw new Error('No session returned from server')
        sessionRef.current = result.data.session
        setSession(result.data.session)
    }, [projectId])

    // ----- setApproach (just stores choice — no step advancement) ------------

    const setApproach = useCallback(async (a: Approach) => {
        setApproachState(a)
        try {
            await openSession()
        } catch (err) {
            console.error('Failed to open upload session:', err)
            toast.error('Failed to connect to server. Please try again.')
        }
    }, [openSession])

    // ----- step navigation (index-based within flow) --------------------------

    const nextStep = useCallback(() => {
        setCurrentStep(prev => {
            const flow = getFlow(approachRef.current ?? Approach.StepByStep)
            const idx = findIndex(flow, prev)
            if (idx < flow.length - 1) return flow[idx + 1]
            return prev
        })
    }, [])

    const prevStep = useCallback((targetStep?: Step) => {
        if (targetStep !== undefined) {
            setCurrentStep(targetStep)
            return
        }
        setCurrentStep(prev => {
            const flow = getFlow(approachRef.current ?? Approach.StepByStep)
            const idx = findIndex(flow, prev)
            if (idx > 0) return flow[idx - 1]
            return prev
        })
    }, [])

    const prevReviewStep = useCallback(() => {
        setCurrentStep(prev => {
            const flow = getFlow(approachRef.current ?? Approach.StepByStep)
            const reviewIdx = findIndex(flow, Step.Review)
            const prevIdx = Math.max(0, reviewIdx - 1)
            return flow[prevIdx]
        })
    }, [])

    // ----- File/path actions --------------------------------------------------

    const setIncludeMasks = useCallback((v: boolean) => {
        setIncludeMasksState(v)
        if (!v) {
            setDisabledMaskState(false)
            setDisabledPatchCsvState(true)
        } else {
            setDisabledMaskState(false)
            if (includePatchCsvRef.current) {
                setDisabledPatchCsvState(false)
            }
        }
    }, [])

    const setIncludePatchCsv = useCallback((v: boolean) => {
        setIncludePatchCsvState(v)
        if (!v) {
            setDisabledPatchCsvState(false)
            setDisabledMaskState(true)
        } else {
            setDisabledPatchCsvState(false)
            if (includeMasksRef.current) {
                setDisabledMaskState(false)
            }
        }
    }, [])

    const setIsFolderForType = useCallback((type: UploadType, value: boolean) => {
        setIsFolderByType(prev => ({ ...prev, [type]: value }))
    }, [])

    const updatePath = useCallback((type: UploadType, path: string) => {
        setPathsByType(prev => ({ ...prev, [type]: path }))
    }, [])

    const addImages = useCallback((files: File[]) => {
        images.current.push(...files)
        setUploadedFileCounts(prev => ({ ...prev, image: images.current.length }))
    }, [])

    const addMasks = useCallback((files: File[]) => {
        masks.current.push(...files)
        setUploadedFileCounts(prev => ({ ...prev, mask: masks.current.length }))
    }, [])

    const addPatchCsvs = useCallback((files: File[]) => {
        patchCsvFiles.current.push(...files)
        setUploadedFileCounts(prev => ({ ...prev, patch_csv: patchCsvFiles.current.length }))
    }, [])

    const setCsvFile = useCallback((file: File | null) => {
        csvFile.current = file
        setUploadedFileCounts(prev => ({ ...prev }))
    }, [])

    // ----- reset --------------------------------------------------------------

    const reset = useCallback(() => {
        setApproachState(null)
        setCurrentStep(Step.ApproachSelection)
        setSession(null)
        setIncludeMasksState(true)
        setIncludePatchCsvState(true)
        setDisabledMaskState(false)
        setDisabledPatchCsvState(false)
        setIsFolderByType({ image: false, mask: false, patch_csv: false })
        setPathsByType({ image: '', mask: '', patch_csv: '' })
        setUploadedFileCounts({ image: 0, mask: 0, patch_csv: 0 })
        images.current = []
        masks.current = []
        patchCsvFiles.current = []
        csvFile.current = null
        sessionRef.current = null
    }, [])

    return {
        approach,
        currentStep,
        session,
        includeMasks,
        includePatchCsv,
        disabledMask,
        disabledPatchCsv,
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
        setIncludeMasks,
        setIncludePatchCsv,
        setIsFolderForType,
        updatePath,
        addImages,
        addMasks,
        addPatchCsvs,
        setCsvFile,
        reset,
    }
}
