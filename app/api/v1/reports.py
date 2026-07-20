from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, status

from app.db.deps import get_db
from app.db.models import Report, User
from app.core.security import get_current_user
from app.core.redis import create_sync_redis_client
from app.api.v1.schemas import ReportCreate, ReportRead, DeleteReportRequest


router = APIRouter(prefix="/reports", tags=["reports"])
REPORT_REDIS_TTL_SECONDS = 3 * 60 * 60
REPORTS_LOCATIONS_KEY = "reports_locations"


@router.post("", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report(
    report_in: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportRead:
    report = Report(
        user_id=current_user.id,
        report_type=report_in.report_type,
        latitude=report_in.latitude,
        longitude=report_in.longitude,
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    report_out = ReportRead.model_validate(report)
    _try_cache_report(report_out)
    return report_out


def _try_cache_report(report: ReportRead) -> None:
    try:
        _cache_report(report)
    except Exception:
        return


def _cache_report(report: ReportRead) -> None:
    redis_client = create_sync_redis_client()
    try:
        report_key = _report_cache_key(report.id)
        redis_client.set(
            report_key,
            report.model_dump_json(),
            ex=REPORT_REDIS_TTL_SECONDS,
        )
        redis_client.geoadd(
            REPORTS_LOCATIONS_KEY,
            (report.longitude, report.latitude, report_key),
        )
        redis_client.expire(REPORTS_LOCATIONS_KEY, REPORT_REDIS_TTL_SECONDS)
    finally:
        redis_client.close()


def _report_cache_key(report_id: object) -> str:
    return f"reports:{report_id}"


@router.post("/deleteReport")
def delete_report(
    payload: DeleteReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    report = db.get(Report, payload.report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    if report.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete another user's report",
        )

    db.delete(report)
    db.commit()

    _try_delete_cached_report(payload.report_id)

    return {"message": "Report deleted"}


def _try_delete_cached_report(report_id: object) -> None:
    try:
        _delete_cached_report(report_id)
    except Exception:
        return


def _delete_cached_report(report_id: object) -> None:
    redis_client = create_sync_redis_client()
    try:
        report_key = _report_cache_key(report_id)
        redis_client.delete(report_key)
        redis_client.zrem(REPORTS_LOCATIONS_KEY, report_key)
    finally:
        redis_client.close()
