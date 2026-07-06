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
    UploadCSVs = 3,
    UploadFileList = 4,
    Review = 5,
    Complete = 6,
}

export const STEP_BY_STEP_FLOW = [
    Step.ApproachSelection,
    Step.UploadImages,
    Step.UploadMasks,
    Step.UploadCSVs,
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

export type UploadType = 'image' | 'mask' | 'csv'

// ---------------------------------------------------------------------------
// Flow helpers
// ---------------------------------------------------------------------------

function getFlow(approach: Approach, includeMasks: boolean, includeCSV: boolean): readonly Step[] {
    if (approach === Approach.StepByStep) {
        let flow = [...STEP_BY_STEP_FLOW]
        if (!includeMasks) flow = flow.filter(s => s !== Step.UploadMasks)
        if (!includeCSV) flow = flow.filter(s => s !== Step.UploadCSVs)
        return flow as typeof STEP_BY_STEP_FLOW
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
    includeCSV: boolean
    isFolderByType: Record<UploadType, boolean>
    pathsByType: Record<UploadType, string>
    uploadedFileCounts: Record<UploadType, number>
    currentFlow: readonly Step[]

    // Refs
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    csvLabels: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>

    // Actions
    setApproach: (a: Approach) => Promise<void>
    nextStep: () => void
    prevStep: (targetStep?: Step) => void
    prevReviewStep: () => void
    setIncludeMasks: (v: boolean) => void
    setIncludeCSV: (v: boolean) => void
    setIsFolderForType: (type: UploadType, value: boolean) => void
    updatePath: (type: UploadType, path: string) => void
    addImages: (files: File[]) => void
    addMasks: (files: File[]) => void
    addCSVLabels: (files: File[]) => void
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
    const [includeMasks, setIncludeMasks] = useState(true)
    const [includeCSV, setIncludeCSV] = useState(true)
    const [isFolderByType, setIsFolderByType] = useState<Record<UploadType, boolean>>({
        image: false,
        mask: false,
        csv: false,
    })
    const [pathsByType, setPathsByType] = useState<Record<UploadType, string>>({
        image: '',
        mask: '',
        csv: '',
    })
    const [uploadedFileCounts, setUploadedFileCounts] = useState<Record<UploadType, number>>({
        image: 0,
        mask: 0,
        csv: 0,
    })

    const images = useRef<File[]>([])
    const masks = useRef<File[]>([])
    const csvLabels = useRef<File[]>([])
    const csvFile = useRef<File | null>(null)

    const sessionRef = useRef<string | null>(null)
    const approachRef = useRef(approach)
    approachRef.current = approach
    const includeMasksRef = useRef(includeMasks)
    includeMasksRef.current = includeMasks
    const includeCSVRef = useRef(includeCSV)
    includeCSVRef.current = includeCSV

    // Current flow (reactive to includeMasks/includeCSV)
    const currentFlow = useMemo(
        () => getFlow(approach ?? Approach.StepByStep, includeMasks, includeCSV),
        [approach, includeMasks, includeCSV],
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
            const flow = getFlow(approachRef.current ?? Approach.StepByStep, includeMasksRef.current, includeCSVRef.current)
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
            const flow = getFlow(approachRef.current ?? Approach.StepByStep, includeMasksRef.current, includeCSVRef.current)
            const idx = findIndex(flow, prev)
            if (idx > 0) return flow[idx - 1]
            return prev
        })
    }, [])

    const prevReviewStep = useCallback(() => {
        setCurrentStep(prev => {
            const flow = getFlow(approachRef.current ?? Approach.StepByStep, includeMasksRef.current, includeCSVRef.current)
            const reviewIdx = findIndex(flow, Step.Review)
            const prevIdx = Math.max(0, reviewIdx - 1)
            return flow[prevIdx]
        })
    }, [])

    // ----- File/path actions --------------------------------------------------

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

    const addCSVLabels = useCallback((files: File[]) => {
        csvLabels.current.push(...files)
        setUploadedFileCounts(prev => ({ ...prev, csv: csvLabels.current.length }))
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
        setIncludeMasks(true)
        setIncludeCSV(true)
        setIsFolderByType({ image: false, mask: false, csv: false })
        setPathsByType({ image: '', mask: '', csv: '' })
        setUploadedFileCounts({ image: 0, mask: 0, csv: 0 })
        images.current = []
        masks.current = []
        csvLabels.current = []
        csvFile.current = null
        sessionRef.current = null
    }, [])

    return {
        approach,
        currentStep,
        session,
        includeMasks,
        includeCSV,
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
        setIncludeMasks,
        setIncludeCSV,
        setIsFolderForType,
        updatePath,
        addImages,
        addMasks,
        addCSVLabels,
        setCsvFile,
        reset,
    }
}
