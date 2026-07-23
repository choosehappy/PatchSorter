import { Outlet } from 'react-router-dom';
import Navigation from '../components/Navigation';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

// TODO: Replace with actual project state/logic
const currentProject = null;

export default function Root() {
    return (
        <div className="d-flex flex-column" style={{ height: '100vh' }}>
            <Navigation currentProject={currentProject} />
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
            <Outlet />
        </div>
    );
}
