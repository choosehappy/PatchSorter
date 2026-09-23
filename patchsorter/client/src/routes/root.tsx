import { Outlet, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getProjectProjectsProjectIdGet } from '../api_client';
import Navigation from '../components/Navigation';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

export default function Root() {
    const { projectId: projectIdParam } = useParams<{ projectId: string }>();

    const { data: project } = useQuery({
        queryKey: ['project', projectIdParam],
        queryFn: () => getProjectProjectsProjectIdGet({ path: { project_id: Number(projectIdParam!) } }).then(r => r.data),
        enabled: projectIdParam !== undefined && !isNaN(Number(projectIdParam!)),
    });

    return (
        <div className="d-flex flex-column" style={{ height: '100vh', overflow: 'hidden' }}>
            <Navigation currentProject={project ? { id: String(project.project_id), name: project.project_name } : null} />
            <ToastContainer
                position="bottom-right"
                autoClose={5000}
                hideProgressBar={false}
                newestOnTop={false}
                closeOnClick={false}
                rtl={false}
                pauseOnFocusLoss
                draggable
                pauseOnHover
                theme="light"
            />
            <div style={{ flex: 1, overflow: 'hidden' }}>
                <Outlet />
            </div>
        </div>
    );
}
