from __future__ import annotations

from sqlalchemy.orm import Session


class PredPatchStore:
    """Data-access methods for a project's prediction tables.

    Manages ``project{N}_pred_patch_latest`` and ``project{N}_pred_patch_last``,
    which store the two most recent prediction epochs for the project.

    Args:
        project_id: Integer ID of the project.  Used to construct the
            project-scoped table names.
        session: An active SQLAlchemy session provided by
            :meth:`~patchsorter.db.db_client.CitusHeadClient.get_session` or
            :meth:`~patchsorter.db.db_client.CitusWorkerClient.get_session`.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        self.project_id = project_id
        self._session = session
        self.table_name = f"project{project_id}_pred_patch_latest"
