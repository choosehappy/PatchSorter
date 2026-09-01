import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useQueries } from '@tanstack/react-query'
import { Container } from 'react-bootstrap'
import { SlickgridReact } from 'slickgrid-react'
import type { Column, GridOption, SlickgridReactInstance } from 'slickgrid-react'
import '@slickgrid-universal/common/dist/styles/css/slickgrid-theme-bootstrap.css'
import type { ProjectResponse, ProjectStatsResponse } from '../api_client'
import { listProjectsProjectsGet, getProjectStatsProjectsProjectIdStatsGet } from '../api_client'
import CreateProjectModal from '../components/landingPage/CreateProjectModal'
import DeleteProjectModal from '../components/landingPage/DeleteProjectModal'
import EditProjectModal from '../components/landingPage/EditProjectModal'
import LandingActionsFooter from '../components/landingPage/LandingActionsFooter'

interface ProjectWithStats extends ProjectResponse {
    num_images?: number | null
    patch_size?: number | null
    num_label_classes?: number | null
    total_objects?: number | null
    labeled_count?: number | null
}

type FormatterResult = string | HTMLElement | DocumentFragment

const nullToDash = (v: unknown): FormatterResult => String(v ?? '—')

const dateFormatter = (v: unknown): FormatterResult => v ? new Date(v as string).toLocaleDateString() : '—'

export default function LandingPage() {
    const queryClient = useQueryClient()
    const navigate = useNavigate()
    const gridRef = useRef<SlickgridReactInstance | null>(null)
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [editingProject, setEditingProject] = useState<ProjectResponse | null>(null)
    const [showEditModal, setShowEditModal] = useState(false)
    const [showDeleteModal, setShowDeleteModal] = useState(false)
    const [projectToDelete, setProjectToDelete] = useState<ProjectResponse | null>(null)

    const { data: projects, isLoading } = useQuery({
        queryKey: ['projects'],
        queryFn: () => listProjectsProjectsGet().then(r => r.data),
    })

    const projectQueries = useQueries({
        queries: (projects ?? []).map(project => ({
            queryKey: ['projectStats', project.project_id],
            queryFn: () => getProjectStatsProjectsProjectIdStatsGet({
                path: { project_id: project.project_id }
            }).then(r => r.data),
            enabled: (projects?.length ?? 0) > 0,
            staleTime: 30_000,
        }))
    })

    const projectsWithStats: (ProjectWithStats & { num_images: number | null; patch_size: number | null; num_label_classes: number | null; total_objects: number | null; labeled_count: number | null })[] = useMemo(() =>
        (projects ?? []).map((project, i) => {
            const stats = projectQueries[i]?.isSuccess ? (projectQueries[i].data as ProjectStatsResponse) : null
            return {
                ...project,
                num_images: stats?.num_images ?? null,
                patch_size: stats?.patch_size ?? null,
                num_label_classes: stats?.num_label_classes ?? null,
                total_objects: stats?.total_objects ?? null,
                labeled_count: stats?.labeled_count ?? null,
            }
        }), [projects, projectQueries])

    const columns = useMemo((): Column[] => [
        { id: 'project_id', name: 'Project ID', field: 'project_id', sortable: true, width: 120 },
        { id: 'project_name', name: 'Project Name', field: 'project_name', sortable: true, width: 200 },
        { id: 'description', name: 'Description', field: 'description', sortable: false, width: 250, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'creation_date', name: 'Creation Date', field: 'creation_ts', sortable: true, width: 130, formatter: (_r: number, _c: number, v: unknown) => dateFormatter(v) },
        { id: 'num_images', name: 'No. images', field: 'num_images', sortable: true, width: 110, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'patch_size', name: 'Patch Size', field: 'patch_size', sortable: true, width: 100, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'num_label_classes', name: 'No. label classes', field: 'num_label_classes', sortable: true, width: 150, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'total_objects', name: 'No. total objects', field: 'total_objects', sortable: true, width: 160, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'labeled_count', name: 'No. labeled objects', field: 'labeled_count', sortable: true, width: 170, formatter: (_r: number, _c: number, v: unknown) => nullToDash(v) },
        { id: 'actions', name: 'Actions', field: 'project_id', sortable: false, width: 180, formatter: (_r: number, _c: number, _v: unknown, _col: Column, dataContext: ProjectWithStats) => {
                const btn = document.createElement('button')
                btn.className = 'btn btn-outline-primary btn-sm me-1'
                btn.textContent = 'Edit'
                btn.onclick = () => {
                    setEditingProject(dataContext)
                    setShowEditModal(true)
                }
                const settingsBtn = document.createElement('button')
                settingsBtn.className = 'btn btn-outline-secondary btn-sm me-1'
                settingsBtn.textContent = 'Settings'
                settingsBtn.disabled = true
                const deleteBtn = document.createElement('button')
                deleteBtn.className = 'btn btn-outline-danger btn-sm'
                deleteBtn.textContent = 'Delete'
                deleteBtn.onclick = () => {
                    setProjectToDelete(dataContext)
                    setShowDeleteModal(true)
                }
                const wrapper = document.createElement('span')
                wrapper.appendChild(btn)
                wrapper.appendChild(settingsBtn)
                wrapper.appendChild(deleteBtn)
                return wrapper
            }
        },
    ], [setEditingProject, setShowEditModal])

    const gridOptions = useMemo<GridOption>(() => ({
        enableAutoResize: true,
        enableCheckboxSelector: false,
        enableSelection: false,
        rowHeight: 40,
        forceFitColumns: true,
        autoResize: { container: '#projects-container' },
        canvasOverridePlugin: undefined,
    }), [])

    const dataset = useMemo(() =>
        isLoading ? [] : projectsWithStats.map(p => ({
            id: p.project_id,
            project_id: p.project_id,
            project_name: p.project_name,
            description: p.description ?? null,
            creation_ts: p.creation_ts ?? null,
            num_images: p.num_images,
            patch_size: p.patch_size,
            num_label_classes: p.num_label_classes,
            total_objects: p.total_objects,
            labeled_count: p.labeled_count,
        })), [isLoading, projectsWithStats])

    useEffect(() => {
        if (gridRef.current) {
            gridRef.current.slickGrid.invalidate()
        }
    }, [dataset])

    const onGridReady = useCallback((reactGrid: SlickgridReactInstance) => {
        gridRef.current = reactGrid
        reactGrid.slickGrid?.onClick.subscribe((e, args) => {
            if ((e.target as HTMLElement).closest('button')) return
            if (!args.grid || args.cell == null) return
            const item = args.grid.getDataItem(args.row) as { project_id: number } | undefined
            if (item?.project_id != null) navigate(`/project/${item.project_id}/`)
        })
    }, [navigate])

    const handleEditSuccess = useCallback(() => {
        setShowEditModal(false)
        setEditingProject(null)
        queryClient.invalidateQueries({ queryKey: ['projects'] })
    }, [queryClient])

    const handleCreateSuccess = useCallback(() => {
        setShowCreateModal(false)
        queryClient.invalidateQueries({ queryKey: ['projects'] })
    }, [queryClient])

    const handleDeleteSuccess = useCallback(() => {
        queryClient.invalidateQueries({ queryKey: ['projects'] })
        setProjectToDelete(null)
    }, [queryClient])

    const containerHeight = useMemo(() => {
        if (isLoading) return 300
        const rows = Math.max(5, projectsWithStats.length)
        return rows * 40 + 60
    }, [isLoading, projectsWithStats.length])

    return (
        <Container fluid className="py-3 d-flex flex-column gap-4" style={{ paddingBottom: 80 }}>
            <section>
                <h5>Projects</h5>
                {isLoading && (
                    <div className="d-flex justify-content-center align-items-center" style={{ height: containerHeight }}>
                        <span className="spinner-border spinner-border-lg text-primary" role="status">
                            <span className="visually-hidden">Loading...</span>
                        </span>
                    </div>
                )}
                {!isLoading && projectsWithStats.length === 0 && (
                    <div className="alert alert-info text-center" role="status">
                        No projects yet. Click <strong>'Create New Project'</strong> below.
                    </div>
                )}
                <div
                    id="projects-container"
                    style={{ height: containerHeight, overflow: 'hidden', display: (!isLoading && projectsWithStats.length > 0) ? 'block' : 'none' }}
                >
                    <SlickgridReact
                        gridId="projects-grid"
                        columns={columns}
                        options={gridOptions}
                        dataset={dataset}
                        onReactGridCreated={e => onGridReady(e.detail)}
                    />
                </div>
            </section>

            <LandingActionsFooter onCreateProject={() => setShowCreateModal(true)} />

            <CreateProjectModal
                show={showCreateModal}
                onClose={() => setShowCreateModal(false)}
                onSuccess={handleCreateSuccess}
            />

            <EditProjectModal
                show={showEditModal}
                project={editingProject}
                onClose={() => {
                    setShowEditModal(false)
                    setEditingProject(null)
                }}
                onSuccess={handleEditSuccess}
            />

            <DeleteProjectModal
                show={showDeleteModal}
                project={projectToDelete}
                onClose={() => setShowDeleteModal(false)}
                onSuccess={handleDeleteSuccess}
            />
        </Container>
    )
}
