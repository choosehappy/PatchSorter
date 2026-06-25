import { Link } from 'react-router-dom';
import { Navbar, Nav, Container } from 'react-bootstrap';
import { CaretRightFill, BellFill } from 'react-bootstrap-icons';
import Badge from 'react-bootstrap/Badge';
import { useState } from 'react';
import { useNotificationCenter } from 'react-toastify/addons/use-notification-center';
import NotificationCenter from './NotificationCenter';

interface Project {
    id: string;
    name: string;
}

interface NavigationProps {
    currentProject: Project | null;
}

const Item = ({ children }: { children: React.ReactNode }) => (
    <>
        <Nav.Item style={{ alignItems: 'center', display: 'flex' }}>
            <CaretRightFill className="text-white" />
        </Nav.Item>
        {children}
    </>
);

const Navigation = ({ currentProject }: NavigationProps) => {
    const [showNotifications, setShowNotifications] = useState(false);
    const notificationCenter = useNotificationCenter();
    const unread = notificationCenter?.unreadCount ?? 0;

    return (
        <>
            <Navbar bg="dark" data-bs-theme="dark">
                <Container fluid>
                    <Nav>
                        <Navbar.Brand as={Link} to="/">PatchSorter</Navbar.Brand>
                        {currentProject && (
                            <Item>
                                <Nav.Link as={Link} to={`/project/${currentProject.id}/summary`}>
                                    {currentProject.name}
                                </Nav.Link>
                            </Item>
                        )}
                        {currentProject && (
                            <Item>
                                <Nav.Link as={Link} to={`/project/${currentProject.id}/labeler`}>
                                    Labeler
                                </Nav.Link>
                            </Item>
                        )}
                    </Nav>
                    <Nav className="justify-content-end">
                        <Nav.Link>Metrics</Nav.Link>
                        <Nav.Link onClick={() => setShowNotifications(true)} className="position-relative d-flex align-items-center">
                            <BellFill className="text-white" />
                            {unread > 0 && (
                                <Badge bg="danger" pill style={{ position: 'absolute', top: '6px', right: '6px', transform: 'translate(50%,-50%)' }}>{unread}</Badge>
                            )}
                            <span className="ms-2">Notifications</span>
                        </Nav.Link>
                        <Nav.Link>Settings</Nav.Link>
                    </Nav>
                </Container>
            </Navbar>
            <NotificationCenter
                show={showNotifications}
                onHide={() => setShowNotifications(false)}
                notificationCenter={notificationCenter}
            />
        </>
    );
};

export default Navigation;
