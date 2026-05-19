
import { Outlet } from 'react-router-dom';
import Navigation from '../components/Navigation';
// TODO: Replace with actual project state/logic
const currentProject = null;

export default function Root() {
    return (
        <>
            <Navigation currentProject={currentProject} />
            <Outlet />
        </>
    );
}
