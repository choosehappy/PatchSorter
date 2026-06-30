from pydantic import BaseModel


class SettingResponse(BaseModel):
    setting_id: int
    project_id: int | None
    setting_key: str
    setting_value: str
    default_value: str
    setting_type: str
    allowed_values: str | None
    disabled: bool

    model_config = {"from_attributes": True}
