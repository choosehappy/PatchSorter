from typing import List

from fastapi import APIRouter, HTTPException

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.api.v1.settings.models import SettingResponse

router = APIRouter()


@router.get("/projects/{project_id}/settings/", response_model=List[SettingResponse])
def list_settings(project_id: int) -> List[SettingResponse]:
    client = get_head_client()
    with client.get_session() as session:
        store = SettingsStore(session)
        rows = store.get_all(project_id)
    return [SettingResponse(**r) for r in rows]
