"""Terms and assignment dates: release date, due date and late due date."""

from datetime import datetime, timezone

from fastapi import HTTPException


def utc(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC so they compare with the tz-aware values Mongo returns."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def term_for(dt: datetime) -> str:
    season = "Spring" if dt.month <= 5 else "Summer" if dt.month <= 7 else "Fall"
    return f"{season} {dt.year}"


def is_released(assignment: dict, now: datetime) -> bool:
    release = utc(assignment.get("release_date"))
    return release is None or release <= now


def deadline(assignment: dict) -> datetime | None:
    """Last moment a submission is accepted: the late due date if there is one, else the due date."""
    return utc(assignment.get("late_due_date")) or utc(assignment.get("due_date"))


def is_late(assignment: dict, now: datetime) -> bool:
    due = utc(assignment.get("due_date"))
    return due is not None and now > due


def check_dates(release: datetime | None, due: datetime | None, late: datetime | None) -> None:
    release, due, late = utc(release), utc(due), utc(late)
    if release and due and release > due:
        raise HTTPException(400, "The release date must be before the due date")
    if late and not due:
        raise HTTPException(400, "Set a due date before adding a late due date")
    if late and due and late < due:
        raise HTTPException(400, "The late due date must be after the due date")
