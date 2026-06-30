import { Link, useLocation } from 'react-router-dom';
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

const Separator = () => (
    <span className="text-white mx-2" style={{ fontSize: '0.8rem', opacity: 0.6 }}>
        <CaretRightFill />
    </span>
);

const Item = ({ children, href }: { children: React.ReactNode; href: string }) => (
    <span className="d-inline-flex align-items-center">
        <Separator />
        {children}
    </span>
);

const Navigation = ({ currentProject }: NavigationProps) => {
    const [showNotifications, setShowNotifications] = useState(false);
    const notificationCenter = useNotificationCenter();
    const unread = notificationCenter?.unreadCount ?? 0;
    const location = useLocation();
    const isLabeler = currentProject && location.pathname === `/project/${currentProject.id}/labeler`;

    return (
        <>
            <Navbar bg="dark" data-bs-theme="dark">
                <Container fluid>
                    <Nav>
                        <Navbar.Brand as={Link} to="/">PatchSorter</Navbar.Brand>
                        {currentProject && (
                            <Item href={`/project/${currentProject.id}/`}>
                                <Nav.Link as={Link} to={`/project/${currentProject.id}/`} className="text-white">
                                    {currentProject.name}
                                </Nav.Link>
                            </Item>
                        )}
                        {currentProject && isLabeler && (
                            <Item href={`/project/${currentProject.id}/labeler`}>
                                <Nav.Link as={Link} to={`/project/${currentProject.id}/labeler`} className="text-white">
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
