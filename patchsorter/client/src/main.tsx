import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import 'bootstrap/dist/css/bootstrap.min.css';
import './index.css'
import Root from './routes/root.tsx'
import LabelingPage from './routes/labelingPage.tsx'
import ProjectPage from './routes/projectPage.tsx'

const queryClient = new QueryClient()

const router = createBrowserRouter([
    {
        path: '/',
        element: <Root />,
        children: [
            { path: '/project/:projectId/labeler', element: <LabelingPage /> },
            { path: '/project/:projectId/project', element: <ProjectPage /> },
        ],
    },
])

createRoot(document.getElementById('root')!).render(
    <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
    </QueryClientProvider>
)
