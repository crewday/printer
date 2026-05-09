from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from printer_app.models import (
    AppConfig,
    CrewdayWorker,
    ReceiptTask,
    TaskBatch,
    WorkerConfig,
)

MOCK_TASK_TITLES = (
    "Review today's Crewday assignments",
    "Confirm task details before starting",
    "Report blockers in Crewday",
)


class TaskSource(Protocol):
    def fetch_task_batch(
        self,
        worker: WorkerConfig,
        *,
        now: datetime,
    ) -> TaskBatch:
        """Return the printable task batch for one configured worker."""


def build_task_source(config: AppConfig) -> TaskSource:
    if config.crewday.source == "crewday_http":
        return CrewdayHttpTaskSource(config)
    return MockTaskSource()


class MockTaskSource:
    def fetch_task_batch(self, worker: WorkerConfig, *, now: datetime) -> TaskBatch:
        tasks = tuple(
            ReceiptTask(
                id=f"mock-{index}",
                title=title,
                property_name="Crewday mock",
                area="Operations",
                scheduled_start=now.replace(minute=0, second=0, microsecond=0)
                + timedelta(minutes=30 * (index - 1)),
                duration_minutes=30,
                priority="normal" if index < 3 else "high",
                status="pending",
                photo_required=index == 3,
                checklist=(
                    "Open the task in Crewday",
                    "Mark blockers before completion",
                )
                if index == 1
                else (),
            )
            for index, title in enumerate(MOCK_TASK_TITLES, start=1)
        )
        return TaskBatch(
            worker_name=worker.name,
            source_label="Mock tasks",
            generated_at=now,
            tasks=tasks,
        )


class CrewdayHttpTaskSource:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def fetch_task_batch(self, worker: WorkerConfig, *, now: datetime) -> TaskBatch:
        if not worker.crewday_user_id:
            raise ValueError(
                f"worker {worker.name!r} needs crewday_user_id for HTTP source"
            )

        local_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(UTC)
        end = (local_start + timedelta(days=1)).astimezone(UTC)
        headers = {}
        if self._config.crewday.api_token:
            headers["Authorization"] = f"Bearer {self._config.crewday.api_token}"
        params = {
            "assignee_user_id": worker.crewday_user_id,
            "scheduled_for_utc_gte": start.isoformat(),
            "scheduled_for_utc_lt": end.isoformat(),
            "limit": "100",
        }
        task_path = "/api/v1/tasks"
        if self._config.crewday.workspace_slug:
            task_path = f"/w/{self._config.crewday.workspace_slug}/api/v1/tasks"
        with httpx.Client(base_url=self._config.crewday.base_url, timeout=10) as client:
            response = client.get(task_path, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        rows = _rows(payload)
        return TaskBatch(
            worker_name=worker.name,
            source_label="Crewday",
            generated_at=now,
            tasks=tuple(_task_from_crewday(row, now) for row in rows),
        )

    def fetch_workers(self) -> tuple[CrewdayWorker, ...]:
        headers = {}
        if self._config.crewday.api_token:
            headers["Authorization"] = f"Bearer {self._config.crewday.api_token}"

        with httpx.Client(base_url=self._config.crewday.base_url, timeout=10) as client:
            for path in self._worker_paths():
                response = client.get(path, headers=headers)
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                return tuple(
                    _worker_from_crewday(row) for row in _rows(response.json())
                )
        return ()

    def _worker_paths(self) -> tuple[str, ...]:
        prefix = ""
        if self._config.crewday.workspace_slug:
            prefix = f"/w/{self._config.crewday.workspace_slug}/api/v1"
        else:
            prefix = "/api/v1"
        return (f"{prefix}/employees", f"{prefix}/users")


def fetch_crewday_workers(config: AppConfig) -> tuple[CrewdayWorker, ...]:
    if config.crewday.source == "crewday_http":
        return CrewdayHttpTaskSource(config).fetch_workers()
    return tuple(
        CrewdayWorker(user_id=worker.crewday_user_id or worker.name, name=worker.name)
        for worker in config.workers
    )


def _task_from_crewday(row: dict[str, Any], now: datetime) -> ReceiptTask:
    scheduled = row.get("scheduled_for_utc") or row.get("scheduled_start")
    scheduled_dt = None
    if isinstance(scheduled, str):
        scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if scheduled_dt.tzinfo is not None and now.tzinfo is not None:
            scheduled_dt = scheduled_dt.astimezone(now.tzinfo)

    checklist_raw = row.get("checklist") or row.get("checklist_items") or []
    checklist = tuple(
        str(item.get("label") or item.get("text") or item) for item in checklist_raw
    )
    return ReceiptTask(
        id=str(row.get("id", "")),
        title=str(row.get("title", "Untitled task")),
        property_name=row.get("property_name") or row.get("property"),
        area=row.get("area") or row.get("area_id"),
        scheduled_start=scheduled_dt,
        time_window=row.get("time_window_local"),
        duration_minutes=row.get("duration_minutes") or row.get("estimated_minutes"),
        priority=str(row.get("priority", "normal")),
        status=str(row.get("state") or row.get("status") or "pending"),
        photo_required=(row.get("photo_evidence") == "required"),
        checklist=checklist,
    )


def _rows(payload: object) -> list[dict[str, Any]]:
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _worker_from_crewday(row: dict[str, Any]) -> CrewdayWorker:
    user_id = row.get("user_id") or row.get("id") or row.get("users_id")
    name = (
        row.get("name")
        or row.get("display_name")
        or row.get("full_name")
        or row.get("email")
        or "Unnamed worker"
    )
    return CrewdayWorker(user_id=str(user_id or ""), name=str(name))
