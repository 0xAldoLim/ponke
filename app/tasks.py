"""Persistent tasks and deterministic ordering, separate from reminders."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.database import Project, Task, utcnow
from app.validation import Clarification, aware, parse_datetime

STATUSES = {"todo", "in_progress", "blocked", "done", "cancelled"}
PRIORITIES = {"low", "medium", "high", "critical"}
OPEN = {"todo", "in_progress", "blocked"}


def priority_score(task: Task, now: datetime, free_minutes: int | None = None) -> int:
    score = {"low": 0, "medium": 20, "high": 40, "critical": 60}[task.priority]
    if task.due_at:
        days = (aware(task.due_at) - now).total_seconds() / 86400
        score += 50 if days < 0 else 35 if days < 1 else 20 if days < 3 else 5 if days < 7 else 0
    if task.status == "blocked":
        score -= 30
    if task.estimated_minutes is not None and free_minutes is not None:
        score += 8 if task.estimated_minutes <= free_minutes else -8
    return score


async def resolve_task(db, user_id, target_id=None, search=None):
    if target_id:
        task = await db.scalar(select(Task).where(Task.user_id == user_id, Task.id == target_id))
        if not task:
            raise Clarification("I couldn't find that task.")
        return task
    if not search:
        raise Clarification("Which task? Give me its title or ID.")
    rows = (
        await db.scalars(
            select(Task)
            .where(Task.user_id == user_id, Task.title.icontains(search, autoescape=True))
            .limit(3)
        )
    ).all()
    if len(rows) != 1:
        raise Clarification(
            "I found several tasks. Please use its ID." if rows else "I couldn't find that task."
        )
    return rows[0]


async def task_action(db, user_id, kind, e, settings):
    if kind == "task.create":
        if not e.title or not e.title.strip():
            raise Clarification("What should I call the task?")
        if e.priority and e.priority not in PRIORITIES:
            raise Clarification("Priority must be low, medium, high, or critical.")
        project_id = None
        if e.project:
            project = await db.scalar(
                select(Project).where(Project.user_id == user_id, Project.name == e.project)
            )
            if not project:
                raise Clarification("I couldn't find that project. Create it first.")
            project_id = project.id
        task = Task(
            user_id=user_id,
            title=e.title.strip()[:250],
            description=e.description or "",
            priority=e.priority or "medium",
            due_at=parse_datetime(e.start, settings.user_timezone) if e.start else None,
            project_id=project_id,
            estimated_minutes=e.estimated_minutes,
        )
        db.add(task)
        await db.flush()
        return (
            f"Added task: {task.title}"
            + (
                f" — due {aware(task.due_at).astimezone(ZoneInfo(settings.user_timezone)):%d %b %H:%M}"
                if task.due_at
                else ""
            )
            + f"\nID: {task.id}"
        )
    if kind == "task.query":
        rows = (
            await db.scalars(select(Task).where(Task.user_id == user_id, Task.status.in_(OPEN)).limit(200))
        ).all()
        now = utcnow()
        if e.search and "overdue" in e.search.casefold():
            rows = [t for t in rows if t.due_at and aware(t.due_at) < now]
        rows.sort(
            key=lambda t: (
                -priority_score(t, now),
                aware(t.due_at) if t.due_at else datetime.max.replace(tzinfo=UTC),
                t.created_at,
            )
        )
        return (
            "\n".join(
                f"{i}. {t.title} [{t.priority}; {t.status}]"
                + (
                    f" — due {aware(t.due_at).astimezone(ZoneInfo(settings.user_timezone)):%d %b %H:%M}"
                    if t.due_at
                    else ""
                )
                + f"\nID: {t.id}"
                for i, t in enumerate(rows[:20], 1)
            )
            or "No open tasks."
        )
    task = await resolve_task(db, user_id, e.target_id, e.search)
    if kind == "task.complete":
        task.status, task.completed_at = "done", utcnow()
    elif kind == "task.update":
        if e.title:
            task.title = e.title[:250]
        if e.description is not None:
            task.description = e.description
        if e.priority:
            task.priority = e.priority
        if e.status:
            if e.status not in STATUSES:
                raise Clarification("Invalid task status.")
            task.status = e.status
            task.completed_at = utcnow() if e.status == "done" else None
        if e.start:
            task.due_at = parse_datetime(e.start, settings.user_timezone)
        if e.estimated_minutes is not None:
            task.estimated_minutes = e.estimated_minutes
    else:
        raise Clarification("Unsupported task action.")
    task.updated_at = utcnow()
    return f"Updated task: {task.title} ({task.status})."


async def project_action(db, user_id, kind, e):
    if kind == "project.create":
        if not e.title:
            raise Clarification("What should I call the project?")
        existing = await db.scalar(select(Project).where(Project.user_id == user_id, Project.name == e.title))
        if existing:
            return f"Project already exists: {existing.name}."
        project = Project(user_id=user_id, name=e.title[:150], description=e.description or "")
        db.add(project)
        return f"Created project: {project.name}."
    rows = (
        await db.scalars(
            select(Project)
            .where(Project.user_id == user_id, Project.status == "active")
            .order_by(Project.name)
        )
    ).all()
    return (
        "\n".join(f"{p.name} — {p.description}" if p.description else p.name for p in rows)
        or "No active projects."
    )
