import enum
from uuid import UUID
from sqlalchemy import Enum, Float, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base_model import BaseModel


class ReportType(str, enum.Enum):
    POLICE = "POLICE"
    FLOODING = "FLOODING"
    ROAD_DANGER = "ROAD_DANGER"
    TRAFFIC_JAM = "TRAFFIC_JAM"
    MISSING_SIGN = "MISSING_SIGN"
    CAR_ACCIDENT = "CAR_ACCIDENT"
    CONSTRUCTION = "CONSTRUCTION"
    SPEED_CAMERA = "SPEED_CAMERA"


class Report(BaseModel):
    __tablename__ = "reports"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, name="report_type"),
        default=ReportType.ROAD_DANGER,
        nullable=False,
    )

    latitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    longitude: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
