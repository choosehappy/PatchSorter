from pydantic import BaseModel


class SettingResponse(BaseModel):
    setting_id: int
    project_id: int
    setting_name: str
    setting_value: str

    model_config = {"from_attributes": True}
