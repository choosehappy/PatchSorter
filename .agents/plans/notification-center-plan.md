# Notification Center – Implementation Plan

## Overview

Add a notification center identical to the one in
[QuickAnnotator v2.0](https://github.com/choosehappy/QuickAnnotator/tree/v2.0).
The center is a Bootstrap `Offcanvas` panel (slide-in from the right) that
displays toast notifications collected by `react-toastify`'s
`useNotificationCenter` hook. Users can filter to unread only, mark all as
read, or clear all notifications. A badge on the navbar bell icon shows the
live unread count.

---

## Reference Implementation

| File | Role |
|------|------|
| `notificationCenter.tsx` | Presentational `<NotificationCenter>` component (Offcanvas panel) |
| `root.tsx` | Renders `<ToastContainer>` only — no notification state |
| `navigation.tsx` | Calls `useNotificationCenter()` internally; renders bell icon with live badge and `<NotificationCenter>` |

---

## Current State

| File | Current state |
|------|---------------|
| `patchsorter/client/src/routes/root.tsx` | Renders `<Navigation>` and `<Outlet>`; no toasts, no notification state |
| `patchsorter/client/src/components/Navigation.tsx` | Bell icon + `showNotifications` state already present; comment `{/* NotificationCenter would go here */}`; `unread` hardcoded to `0` |
| `patchsorter/client/package.json` | `react-toastify` is **not** installed |

---

## Steps

### Step 1 – Install `react-toastify`

```bash
cd patchsorter/client
npm install react-toastify
```

`react-toastify` ships the `useNotificationCenter` addon starting from v9+.

---

### Step 2 – Create `NotificationCenter.tsx`

**File:** `patchsorter/client/src/components/NotificationCenter.tsx`

Model this directly after the QuickAnnotator component:

```tsx
import { useState } from "react";
import Offcanvas from "react-bootstrap/Offcanvas";
import Button from "react-bootstrap/Button";
import ListGroup from "react-bootstrap/ListGroup";
import Badge from "react-bootstrap/Badge";

type Props = {
    show: boolean;
    onHide: () => void;
    /** Object returned from useNotificationCenter() */
    notificationCenter: any;
};

export default function NotificationCenter({ show, onHide, notificationCenter }: Props) {
    const {
        notifications = [],
        clear,
        markAllAsRead,
        markAsRead,
        remove,
        unreadCount,
    } = notificationCenter || {};

    const [showUnreadOnly, setShowUnreadOnly] = useState(true);

    const list = showUnreadOnly
        ? (notifications || []).filter((n: any) => !n.read)
        : (notifications || []);

    return (
        <Offcanvas show={show} onHide={onHide} placement="end">
            <Offcanvas.Header closeButton>
                <Offcanvas.Title>
                    Notifications{" "}
                    <Badge bg="secondary">{unreadCount || 0}</Badge>
                </Offcanvas.Title>
            </Offcanvas.Header>
            <Offcanvas.Body>
                <div className="d-flex justify-content-between align-items-center mb-2">
                    <div>
                        <input
                            id="unread-filter"
                            type="checkbox"
                            checked={showUnreadOnly}
                            onChange={() => setShowUnreadOnly((v) => !v)}
                        />{" "}
                        <label htmlFor="unread-filter">Only show unread</label>
                    </div>
                    <div>
                        <Button
                            variant="outline-secondary"
                            size="sm"
                            onClick={markAllAsRead}
                            className="me-2"
                        >
                            Mark all read
                        </Button>
                        <Button variant="outline-danger" size="sm" onClick={clear}>
                            Clear
                        </Button>
                    </div>
                </div>

                {!list || list.length === 0 ? (
                    <div className="text-center text-muted">Your queue is empty!</div>
                ) : (
                    <ListGroup style={{ maxWidth: "350px", margin: "0 auto" }}>
                        {list.map((n: any) => (
                            <ListGroup.Item
                                key={n.id}
                                className="d-flex justify-content-between align-items-start"
                            >
                                <div>
                                    <div style={{ fontWeight: n.read ? "normal" : "600" }}>
                                        {n.content}
                                    </div>
                                    {n.createdAt && (
                                        <div className="text-muted small">
                                            {new Date(n.createdAt).toLocaleString()}
                                        </div>
                                    )}
                                </div>
                            </ListGroup.Item>
                        ))}
                    </ListGroup>
                )}
            </Offcanvas.Body>
        </Offcanvas>
    );
}
```

---

### Step 3 – Update `root.tsx`

Add `<ToastContainer>` and the CSS import. **Do not** call `useNotificationCenter()` here — `Navigation` owns that hook.

```tsx
import { Outlet } from "react-router-dom";
import Navigation from "../components/Navigation";
import { ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

const currentProject = null; // TODO: replace with real state

export default function Root() {
    return (
        <div className="d-flex flex-column" style={{ height: "100vh" }}>
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
```

---

### Step 4 – Update `Navigation.tsx`

Changes:
1. Call `useNotificationCenter()` **inside** the component (matching QuickAnnotator exactly — no prop needed).
2. Derive `unread` from `notificationCenter.unreadCount`.
3. Remove `notificationCenter` from `NavigationProps`.
4. Import and render `<NotificationCenter>`, passing `show`, `onHide`, and `notificationCenter`.
5. Remove the placeholder comment.

```tsx
import { Link } from "react-router-dom";
import { Navbar, Nav, NavItem, Container } from "react-bootstrap";
import { CaretRightFill, BellFill } from "react-bootstrap-icons";
import Badge from "react-bootstrap/Badge";
import { useState } from "react";
import { useNotificationCenter } from "react-toastify/addons/use-notification-center";
import NotificationCenter from "./NotificationCenter";

interface Project {
    id: string;
    name: string;
}

interface NavigationProps {
    currentProject: Project | null;
}

// @ts-ignore
const Item = ({ children }) => (
    <>
        <NavItem style={{ alignItems: "center", display: "flex" }}>
            <CaretRightFill className="text-white" />
        </NavItem>
        {children}
    </>
);

const Navigation = ({ currentProject }: NavigationProps) => {
    const [showNotifications, setShowNotifications] = useState(false);
    // Call the hook here so the unread count is available in the navbar
    const notificationCenter = useNotificationCenter();
    const unread = (notificationCenter && notificationCenter.unreadCount)
        ? notificationCenter.unreadCount
        : 0;

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
                        <Nav.Link
                            onClick={() => setShowNotifications(true)}
                            className="position-relative d-flex align-items-center"
                        >
                            <BellFill className="text-white" />
                            {unread > 0 && (
                                <Badge
                                    bg="danger"
                                    pill
                                    style={{
                                        position: "absolute",
                                        top: "6px",
                                        right: "6px",
                                        transform: "translate(50%,-50%)",
                                    }}
                                >
                                    {unread}
                                </Badge>
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
```

---

## File Change Summary

| File | Action |
|------|--------|
| `patchsorter/client/package.json` | Add `react-toastify` dependency (via `npm install`) |
| `patchsorter/client/src/components/NotificationCenter.tsx` | **Create** – Offcanvas panel component |
| `patchsorter/client/src/routes/root.tsx` | **Update** – add `<ToastContainer>` and CSS import only |
| `patchsorter/client/src/components/Navigation.tsx` | **Update** – call `useNotificationCenter()` internally; remove hardcoded `unread = 0`; render `<NotificationCenter>`; no new props |

---

## Data Flow

```
root.tsx
  <ToastContainer />  ◄──  toast(…) calls anywhere in the app
       │
       └─► feeds useNotificationCenter() automatically

Navigation.tsx
  useNotificationCenter() ──► notificationCenter object
       │
       ├─► unreadCount ──► badge on bell icon
       │
       └─► <NotificationCenter notificationCenter={…} />
                 │
                 ├─ notifications list (filtered by read/unread)
                 ├─ markAllAsRead()
                 └─ clear()
```

Anywhere in the app a notification can be triggered with:
```ts
import { toast } from "react-toastify";
toast("Patches exported successfully.");
toast.error("Failed to load image.");
```

The toast appears bottom-right **and** is automatically added to the
notification center's history list.

---

## Dependencies Added

| Package | Why |
|---------|-----|
| `react-toastify` | `toast()` API + `useNotificationCenter` hook + `<ToastContainer>` |

No other new dependencies are required; `react-bootstrap` Offcanvas and Badge
are already available.
