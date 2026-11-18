from pydantic import BaseModel


class DLActorState(BaseModel):
    training_enabled: bool    # True = active, False = frozen
