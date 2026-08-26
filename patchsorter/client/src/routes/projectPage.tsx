import { useParams } from 'react-router-dom'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Container } from 'react-bootstrap'
import { toast } from 'react-toastify'
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css'
import LabelClassesTable from '../components/projectPage/LabelClassesTable'
import ImagesTable from '../components/projectPage/ImagesTable'
import ActionsFooter from '../components/projectPage/ActionsFooter'
import UploadWizardModal from '../components/projectPage/UploadWizardModal'
import CreateLabelClassModal from '../components/projectPage/CreateLabelClassModal'
import {
    getProjectProjectsProjectIdGet,
    listLabelClassesProjectsProjectIdLabelClassesGet,
    listImagesProjectsProjectIdImagesGet,
} from '../api_client'

export default function ProjectPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>()
    const projectId = Number(projectIdParam)
    const queryClient = useQueryClient()
    const [selectedImageIds, setSelectedImageIds] = useState<Set<number>>(new Set())
    const [selectedLabelClassIds, setSelectedLabelClassIds] = useState<Set<number>>(new Set())
    const [showUploadWizard, setShowUploadWizard] = useState(false)
    const [showCreateLabelClass, setShowCreateLabelClass] = useState(false)

    const { data: project, isLoading: projectLoading } = useQuery({
        queryKey: ['project', projectId],
        queryFn: () => getProjectProjectsProjectIdGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: labelClasses, isLoading: labelClassesLoading } = useQuery({
        queryKey: ['labelClasses', projectId],
        queryFn: () => listLabelClassesProjectsProjectIdLabelClassesGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: images, isLoading: imagesLoading } = useQuery({
        queryKey: ['projectImages', projectId],
        queryFn: () => listImagesProjectsProjectIdImagesGet({ path: { project_id: projectId } }).then(r => r.data),
    })

    return (
        <Container fluid className="py-3 d-flex flex-column gap-4" style={{ paddingBottom: 80 }}>
            <div>
                <h5>Description</h5>
                <p className="mb-0">
                    {projectLoading ? (
                        <span className="spinner-border spinner-border-sm" role="status" />
                    ) : project?.description ? (
                        project.description
                    ) : (
                        <span className="text-muted">—</span>
                    )}
                </p>
            </div>
            <LabelClassesTable
                projectId={projectId}
                labelClasses={labelClasses ?? []}
                isLoading={labelClassesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['labelClasses', projectId] })}
                selectedIds={selectedLabelClassIds}
                onSelectionChange={setSelectedLabelClassIds}
            />
            <ImagesTable
                projectId={projectId}
                images={images ?? []}
                labelClasses={labelClasses ?? []}
                isLoading={imagesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['projectImages', projectId] })}
                selectedIds={selectedImageIds}
                onSelectionChange={setSelectedImageIds}
            />
            <ActionsFooter
                projectId={projectId}
                selectedImageIds={selectedImageIds}
                selectedLabelClassIds={selectedLabelClassIds}
                onClearImageSelection={() => setSelectedImageIds(new Set())}
                onClearLabelClassSelection={() => setSelectedLabelClassIds(new Set())}
                onOpenUploadWizard={() => setShowUploadWizard(true)}
                onCreateLabelClass={() => setShowCreateLabelClass(true)}
            />
            {showUploadWizard && (
                <UploadWizardModal
                    projectId={projectId}
                    onClose={() => setShowUploadWizard(false)}
                />
            )}
            {showCreateLabelClass && (
                <CreateLabelClassModal
                    projectId={projectId}
                    show={showCreateLabelClass}
                    onClose={() => setShowCreateLabelClass(false)}
                    onSuccess={() => {
                        queryClient.invalidateQueries({ queryKey: ['labelClasses', projectId] })
                        toast.success('Label class created successfully')
                    }}
                />
            )}
        </Container>
    )
}
