from typing import List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from patchsorter.db.head_client import get_client as get_head_client
from patchsorter.db.head_client.settings import SettingsStore, ResolvedSetting, SettingDisabledError
from pydantic import BaseModel

router = APIRouter()


class UpdateSettingRequest(BaseModel):
    value: str


@router.get("/settings/", response_model=List[ResolvedSetting])
def list_settings(project_id: Optional[int] = None, scope: Optional[str] = None) -> List[ResolvedSetting]:
    client = get_head_client()
    with client.get_session() as session:
        store = SettingsStore(session)
        rows = store.get_all_raw(project_id=project_id, scope=scope)
    return list(rows.values())


@router.patch("/settings/{setting_key}", response_model=ResolvedSetting)
def update_setting(
    setting_key: str,
    body: UpdateSettingRequest,
    project_id: Optional[int] = None,
) -> ResolvedSetting:
    client = get_head_client()
    with client.get_session() as session:
        store = SettingsStore(session)
        try:
            store.update(setting_key, body.value, project_id)
        except SettingDisabledError:
            raise HTTPException(status_code=403, detail=f"Setting '{setting_key}' is read-only")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        session.commit()
        resolved = store.get_raw(setting_key, project_id)
        return resolved
