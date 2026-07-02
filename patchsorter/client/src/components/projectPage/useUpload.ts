import { useState, useRef, useCallback } from 'react'
import { toast } from 'react-toastify'
import { openUploadSession } from '../../api_client'
export type { ReviewRow } from '../../api_client'

export type UploadApproach = 'stepByStep' | 'csvFileList'
export type UploadType = 'image' | 'mask' | 'csv'

// ---------------------------------------------------------------------------
// Step navigation helpers
// ---------------------------------------------------------------------------

export function computeNextStep(
    step: number,
    approach: UploadApproach | null,
    includeMasks: boolean,
    includeCSV: boolean,
): number {
    if (approach === 'csvFileList') {
        const next: Record<number, number> = { 0: 4, 4: 5, 5: 6 }
        return next[step] ?? step + 1
    }
    // step-by-step
    if (step === 0) return 1
    if (step === 1) return includeMasks ? 2 : includeCSV ? 3 : 5
    if (step === 2) return includeCSV ? 3 : 5
    if (step === 3) return 5
    if (step === 5) return 6
    return step + 1
}

export function computePrevStep(
    step: number,
    approach: UploadApproach | null,
    includeMasks: boolean,
    includeCSV: boolean,
): number {
    if (approach === 'csvFileList') {
        const prev: Record<number, number> = { 4: 0, 5: 4, 6: 5 }
        return prev[step] ?? Math.max(0, step - 1)
    }
    // step-by-step
    if (step === 2) return 1
    if (step === 3) return includeMasks ? 2 : 1
    if (step === 5) {
        if (includeCSV) return 3
        if (includeMasks) return 2
        return 1
    }
    return Math.max(0, step - 1)
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface UseUploadReturn {
    // React state (drive re-renders)
    approach: UploadApproach | null
    currentStep: number
    session: string | null
    includeMasks: boolean
    includeCSV: boolean
    isFolderByType: Record<UploadType, boolean>
    pathsByType: Record<UploadType, string>
    uploadedFileCounts: Record<UploadType, number>

    // Refs (mutated without re-renders; read at validation time)
    images: React.MutableRefObject<File[]>
    masks: React.MutableRefObject<File[]>
    csvLabels: React.MutableRefObject<File[]>
    csvFile: React.MutableRefObject<File | null>

    // Actions
    setApproach: (a: UploadApproach) => Promise<void>
    nextStep: () => void
    prevStep: (targetStep?: number) => void
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
    const [approach, setApproachState] = useState<UploadApproach | null>(null)
    const [currentStep, setCurrentStep] = useState(0)
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
    // Tracks file counts so UI re-renders when files are added (files themselves live in refs)
    const [uploadedFileCounts, setUploadedFileCounts] = useState<Record<UploadType, number>>({
        image: 0,
        mask: 0,
        csv: 0,
    })

    const images = useRef<File[]>([])
    const masks = useRef<File[]>([])
    const csvLabels = useRef<File[]>([])
    const csvFile = useRef<File | null>(null)

    // Mirror refs for reading inside async callbacks without stale closure issues
    const sessionRef = useRef<string | null>(null)
    const approachRef = useRef(approach)
    approachRef.current = approach
    const includeMasksRef = useRef(includeMasks)
    includeMasksRef.current = includeMasks
    const includeCSVRef = useRef(includeCSV)
    includeCSVRef.current = includeCSV

    // ----- openSession --------------------------------------------------------

    const openSession = useCallback(async () => {
        if (sessionRef.current) return
        const result = await openUploadSession({ path: { project_id: projectId } })
        if (!result.data?.session) throw new Error('No session returned from server')
        sessionRef.current = result.data.session
        setSession(result.data.session)
    }, [projectId])

    // ----- setApproach --------------------------------------------------------
    // Immediately advances from step 0 and lazily opens the session.

    const setApproach = useCallback(async (a: UploadApproach) => {
        setApproachState(a)
        try {
            await openSession()
        } catch (err) {
            console.error('Failed to open upload session:', err)
            toast.error('Failed to connect to server. Please try again.')
            return  // Don't advance if session creation fails
        }
        setCurrentStep(1)
    }, [openSession])

    // ----- nextStep / prevStep ------------------------------------------------

    const nextStep = useCallback(() => {
        setCurrentStep(prev =>
            computeNextStep(prev, approachRef.current, includeMasksRef.current, includeCSVRef.current),
        )
    }, [])

    const prevStep = useCallback((targetStep?: number) => {
        if (targetStep !== undefined) {
            setCurrentStep(targetStep)
        } else {
            setCurrentStep(prev =>
                computePrevStep(prev, approachRef.current, includeMasksRef.current, includeCSVRef.current),
            )
        }
    }, [])

    const prevReviewStep = useCallback(() => {
        setCurrentStep(() => {
            if (approachRef.current === 'csvFileList') return 4
            if (includeCSVRef.current) return 3
            if (includeMasksRef.current) return 2
            return 1
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
        // Force re-render so canProceed (which reads csvFile.current) recomputes
        setUploadedFileCounts(prev => ({ ...prev }))
    }, [])

    // ----- reset --------------------------------------------------------------

    const reset = useCallback(() => {
        setApproachState(null)
        setCurrentStep(0)
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
