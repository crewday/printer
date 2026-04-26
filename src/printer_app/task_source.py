from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from printer_app.models import AppConfig, ReceiptTask, TaskBatch, WorkerConfig


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
            for index, title in enumerate(worker.tasks, start=1)
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

        start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
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
        rows = payload.get("data", payload if isinstance(payload, list) else [])
        return TaskBatch(
            worker_name=worker.name,
            source_label="Crewday",
            generated_at=now,
            tasks=tuple(_task_from_crewday(row) for row in rows),
        )


def _task_from_crewday(row: dict[str, Any]) -> ReceiptTask:
    scheduled = row.get("scheduled_for_utc") or row.get("scheduled_start")
    scheduled_dt = None
    if isinstance(scheduled, str):
        scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))

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
