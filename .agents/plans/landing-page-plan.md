# Landing Page Implementation Plan

## Goal
Create a landing page at the root path `/` that lists and manages all projects.

---

## Backend Changes

### 1. Add `POST /projects/` endpoint

**File:** `patchsorter/api/v1/project/routes.py`

Add a new endpoint that creates a project:

```python
@router.post("/projects/", response_model=ProjectResponse)
def create_project(
    name: str = Form(...),
    description: Optional[str] = Form(None),
) -> ProjectResponse:
    client = get_head_client()
    with client.get_session() as session:
        store = ProjectStore(session)
        row = store.create(name=name, description=description)
    return ProjectResponse(**row)
```

**Note:** Uses `Form` data (not JSON body) for consistency with existing upload endpoints. Alternatively, use a Pydantic request body model (`CreateProjectRequest`) if JSON is preferred.

**Existing infrastructure this relies on:**
- `ProjectStore.create()` — already implemented in `patchsorter/db/head_client/project.py:30`
- `ProjectResponse` — already defined in `patchsorter/api/v1/project/models.py:7`

### 2. No other backend changes needed

The following endpoints already exist and serve the landing page requirements:

| Endpoint | Location | Purpose |
|----------|----------|---------|
| `GET /projects/` | `routes.py:16` | List all projects |
| `GET /projects/{project_id}/stats/` | `routes.py:37` | Stats per project (num_images, patch_size, num_label_classes, total_objects, labeled_count, creation_date, modification_date) |
| `PUT /projects/{project_id}` | `routes.py:97` | Edit project name/description |

---

## Frontend Changes

### 3. New file: `patchsorter/client/src/routes/landingPage.tsx`

**Purpose:** Main landing page component showing a project list table.

**Data fetching:**
- `listProjectsProjectsGet()` — fetches all projects (project_id, project_name, description, creation_ts)
- `getProjectStatsProjectsProjectIdStatsGet({ path: { project_id } })` — fetches stats per project

**Stats columns (derived from `GET /projects/{id}/stats/`):**
| Column | Source | Notes |
|--------|--------|-------|
| No. images | `num_images` | |
| Patch Size | `patch_size` | Nullable — show "—" if null |
| No. label classes | `num_label_classes` | |
| No. total objects | `total_objects` | |
| No. labeled objects | `labeled_count` | |

**Static columns (from `GET /projects/`):**
| Column | Source |
|--------|--------|
| Project id | `project_id` |
| Project name | `project_name` |
| Description | `description` |
| Creation Date | `creation_ts` (formatted as YYYY-MM-DD) |

**Action column:**
- Settings button (disabled / `disabled` attribute)
- Edit button → links to `/project/{projectId}/`

**Implementation approach:**
- Use **SlickGrid** (`react-slickgrid`) for the project list instead of a simple HTML table
- Use `useQuery` from `@tanstack/react-query` for the project list
- Use `useQueries` or individual `useQuery` calls with `enabled` per row to fetch stats for each project
- Stats should be deduplicated via react-query cache (same query key = same result)
- Loading state: show spinner while project list loads; stats columns show "—" while loading per-row
- Empty state: show message "No projects yet. Click 'Create New Project' below."
- Grid columns should be sortable and filterable
- Grid should support column resizing and reordering
- Row selection should be disabled (read-only grid)

### 4. New file: `patchsorter/client/src/components/landingPage/CreateProjectModal.tsx`

**Purpose:** Modal form for creating a new project.

**Fields:**
- Project name (required text input)
- Description (optional textarea)

**Behavior:**
- Opens via prop or context from parent
- On submit: calls `POST /projects/` with name + description
- On success: closes modal, triggers project list refetch
- On error: shows error message

**Components to reuse:**
- `react-bootstrap` Modal (`Modal`, `Form`, `Button`)
- Pattern similar to `UploadWizardModal` (already exists in codebase)

### 5. New file: `patchsorter/client/src/components/landingPage/EditProjectModal.tsx`

**Purpose:** Modal form for editing an existing project.

**Trigger:** User clicks the "Edit" button in the SlickGrid row action column.

**Fields (pre-populated with existing project data):**
- Project name (required text input, pre-filled with current `project_name`)
- Description (optional textarea, pre-filled with current `description`)

**Behavior:**
- Opens when user clicks "Edit" on a project row in the grid
- On submit: calls `PUT /projects/{project_id}` with updated name + description
- On success: closes modal, triggers project list refetch via react-query
- On error: shows error message via toast
- Closing the modal (via backdrop click, X button, or Escape key) triggers the PUT request if changes were made
- If no changes were made, closing simply dismisses the modal without API call

**State management:**
- Track whether form has been modified (dirty state)
- If dirty and user attempts to close: show confirmation dialog ("Discard changes?")
- If not dirty: close immediately without confirmation

**Components to reuse:**
- `react-bootstrap` Modal (`Modal`, `Form`, `Button`)
- Pattern similar to `CreateProjectModal` and `UploadWizardModal`

**API integration:**
- Uses `updateProjectProjectsProjectIdPut({ path: { project_id }, data: { name, description } })`
- Project ID passed as prop from the grid row action handler

### 6. Modify: `patchsorter/client/src/main.tsx`

**Changes:**
- Import `LandingPage` from `./routes/landingPage`
- Add root route: `{ path: '/', element: <LandingPage /> }`
- The `/` route is a child of the existing `Root` route (which provides Navigation + ToastContainer via `Outlet`)

**Before:**
```tsx
const router = createBrowserRouter([
    {
        path: '/',
        element: <Root />,
        children: [
            { path: '/project/:projectId/', element: <ProjectPage /> },
            { path: '/project/:projectId/labeler', element: <LabelingPage /> },
        ],
    },
])
```

**After:**
```tsx
const router = createBrowserRouter([
    {
        path: '/',
        element: <Root />,
        children: [
            { index: true, element: <LandingPage /> },
            { path: '/project/:projectId/', element: <ProjectPage /> },
            { path: '/project/:projectId/labeler', element: <LabelingPage /> },
        ],
    },
])
```

**Key:** Use `index: true` (not `path: '/'`) so it renders as the default child of Root when no sub-path matches.

### 7. Modify: `patchsorter/client/src/components/Navigation.tsx`

**Change:** Add a "Projects" or home link to `/` in the navbar.

**Current:** Navbar.Brand links to `/` already — no change needed here since `<Navbar.Brand as={Link} to="/">PatchSorter</Navbar.Brand>` already points to root.

**Optional improvement:** Show a "Projects" text or icon link alongside the brand for discoverability.

---

## API Client Regeneration

After adding the `POST /projects/` endpoint, regenerate the TypeScript client:

```
cd patchsorter/client && npm run generate  # or equivalent command
```

This will add the `createProjectProjectsPost` function to `src/api_client/sdk.gen.ts`.

---

## Implementation Order

1. Backend: Add `POST /projects/` endpoint in `routes.py`
2. Frontend: Create `landingPage.tsx` component with SlickGrid
3. Frontend: Create `CreateProjectModal.tsx` component
4. Frontend: Create `EditProjectModal.tsx` component
5. Frontend: Update `main.tsx` router with index route
6. Frontend: Regenerate API client
7. Frontend: Wire up modals to regenerated API client functions
8. Frontend: Wire up SlickGrid row actions to EditProjectModal
9. Optional: Update Navigation if desired

---

## Files Summary

| Action | File |
|--------|------|
| Modify | `patchsorter/api/v1/project/routes.py` — add POST endpoint |
| **New** | `patchsorter/client/src/routes/landingPage.tsx` |
| **New** | `patchsorter/client/src/components/landingPage/CreateProjectModal.tsx` |
| **New** | `patchsorter/client/src/components/landingPage/EditProjectModal.tsx` |
| Modify | `patchsorter/client/src/main.tsx` — add index route |
| (Optional) | `patchsorter/client/src/components/Navigation.tsx` — add Projects link |
| Auto-regen | `patchsorter/client/src/api_client/` — after POST endpoint added |
