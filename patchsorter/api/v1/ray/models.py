from pydantic import BaseModel


class DLActorState(BaseModel):
    termination_signal: bool  # True = shutdown requested
    training_enabled: bool    # True = active, False = frozen
