import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Container } from 'react-bootstrap'
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css'
import MetadataSection from '../components/projectPage/MetadataSection'
import LabelClassesTable from '../components/projectPage/LabelClassesTable'
import ImagesTable from '../components/projectPage/ImagesTable'
import {
    getProjectApiV1ProjectsProjectIdGet,
    getProjectStatsApiV1ProjectsProjectIdStatsGet,
    listSettingsApiV1ProjectsProjectIdSettingsGet,
    listLabelClassesApiV1ProjectsProjectIdLabelClassesGet,
    listImagesApiV1ProjectsProjectIdImagesGet,
} from '../api_client'

export default function ProjectPage() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>()
    const projectId = Number(projectIdParam)
    const queryClient = useQueryClient()

    const { data: project, isLoading: projectLoading } = useQuery({
        queryKey: ['project', projectId],
        queryFn: () => getProjectApiV1ProjectsProjectIdGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: stats, isLoading: statsLoading } = useQuery({
        queryKey: ['projectStats', projectId],
        queryFn: () => getProjectStatsApiV1ProjectsProjectIdStatsGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: settings, isLoading: settingsLoading } = useQuery({
        queryKey: ['projectSettings', projectId],
        queryFn: () => listSettingsApiV1ProjectsProjectIdSettingsGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: labelClasses, isLoading: labelClassesLoading } = useQuery({
        queryKey: ['labelClasses', projectId],
        queryFn: () => listLabelClassesApiV1ProjectsProjectIdLabelClassesGet({ path: { project_id: projectId } }).then(r => r.data),
    })
    const { data: images, isLoading: imagesLoading } = useQuery({
        queryKey: ['projectImages', projectId],
        queryFn: () => listImagesApiV1ProjectsProjectIdImagesGet({ path: { project_id: projectId } }).then(r => r.data),
    })

    return (
        <Container fluid className="py-3 d-flex flex-column gap-4">
            <MetadataSection
                project={project}
                projectLoading={projectLoading}
                stats={stats}
                statsLoading={statsLoading}
                settings={settings}
                settingsLoading={settingsLoading}
            />
            <LabelClassesTable
                projectId={projectId}
                labelClasses={labelClasses ?? []}
                isLoading={labelClassesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['labelClasses', projectId] })}
            />
            <ImagesTable
                projectId={projectId}
                images={images ?? []}
                labelClasses={labelClasses ?? []}
                isLoading={imagesLoading}
                onMutated={() => queryClient.invalidateQueries({ queryKey: ['projectImages', projectId] })}
            />
        </Container>
    )
}
