from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, status

from app.db.deps import get_db
from app.db.models import Report, User
from app.core.security import get_current_user
from app.api.v1.schemas import ReportCreate, ReportRead


router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(
    report_in: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Report:
    report = Report(
        user_id=current_user.id,
        report_type=report_in.report_type,
        latitude=report_in.latitude,
        longitude=report_in.longitude,
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    return report
