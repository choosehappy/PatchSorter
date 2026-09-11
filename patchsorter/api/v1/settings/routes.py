from typing import List, Optional

from fastapi import APIRouter

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.settings import SettingsStore, ResolvedSetting

router = APIRouter()


@router.get("/projects/{project_id}/settings/", response_model=List[ResolvedSetting])
def list_settings(project_id: int, scope: Optional[str] = None) -> List[ResolvedSetting]:
    client = get_head_client()
    with client.get_session() as session:
        store = SettingsStore(session)
        rows = store.get_all_raw(project_id=project_id, scope=scope)
    return list(rows.values())
