from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str
    timestamp: datetime
