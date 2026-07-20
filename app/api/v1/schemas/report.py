from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ReportType


class ReportCreate(BaseModel):
    report_type: ReportType = ReportType.ROAD_DANGER
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    report_type: ReportType
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime


class DeleteReportRequest(BaseModel):
    report_id: UUID