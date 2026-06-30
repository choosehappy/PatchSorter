import { Table } from 'react-bootstrap'
import type { ProjectResponse, ProjectStatsResponse, SettingResponse } from '../../api_client'

interface MetadataSectionProps {
    project?: ProjectResponse
    projectLoading: boolean
    stats?: ProjectStatsResponse
    statsLoading: boolean
    settings?: SettingResponse[]
    settingsLoading: boolean
}

const SPINNER = <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />

function Cell({ loading, value }: { loading: boolean; value?: React.ReactNode }) {
    return loading ? SPINNER : <>{value ?? '—'}</>
}

export default function MetadataSection({ project, projectLoading, stats, statsLoading, settings, settingsLoading }: MetadataSectionProps) {
    const patchSize = settings?.find(s => s.setting_key === 'patch_size')?.setting_value

    return (
        <section>
            <h5>Project Metadata</h5>
            <Table bordered hover size="sm" style={{ maxWidth: 600 }}>
                <tbody>
                    <tr><td>Project Name</td><td><Cell loading={projectLoading} value={project?.project_name} /></td></tr>
                    <tr><td>Description</td><td><Cell loading={projectLoading} value={project?.description} /></td></tr>
                    <tr><td>Creation Date</td><td><Cell loading={projectLoading} value={project?.creation_ts ? new Date(project.creation_ts).toLocaleString() : undefined} /></td></tr>
                    <tr><td>Modification Date</td><td><Cell loading={statsLoading} value={stats?.modification_date ? new Date(stats.modification_date).toLocaleString() : undefined} /></td></tr>
                    <tr><td>No. of Images</td><td><Cell loading={statsLoading} value={stats?.num_images} /></td></tr>
                    <tr><td>Patch Size</td><td><Cell loading={settingsLoading} value={patchSize} /></td></tr>
                    <tr><td>No. of Label Classes</td><td><Cell loading={statsLoading} value={stats?.num_label_classes} /></td></tr>
                    <tr><td>Total Objects</td><td><Cell loading={statsLoading} value={stats?.total_objects} /></td></tr>
                    <tr><td>Labeled</td><td><Cell loading={statsLoading} value={stats?.labeled_count} /></td></tr>
                </tbody>
            </Table>
        </section>
    )
}
