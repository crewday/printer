from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

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
        local_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(UTC)
        end = (local_start + timedelta(days=1)).astimezone(UTC)
        params = {
            "scheduled_for_utc_gte": start.isoformat(),
            "scheduled_for_utc_lt": end.isoformat(),
            "limit": "500",
        }
        if worker.crewday_user_id:
            params["assignee_user_id"] = worker.crewday_user_id

        with self._client() as client:
            rows = self._fetch_task_rows(client, params)
        return TaskBatch(
            worker_name=worker.name,
            source_label="Crewday",
            generated_at=now,
            tasks=tuple(self._task_from_row(row, now) for row in rows),
        )

    def fetch_workers(self) -> tuple[CrewdayWorker, ...]:
        with self._client() as client:
            for path in self._worker_paths():
                response = client.get(path, headers=self._headers())
                if response.status_code in {401, 403, 404}:
                    continue
                response.raise_for_status()
                return tuple(
                    _worker_from_crewday(row) for row in _rows(response.json())
                )
        return ()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._config.crewday.base_url,
            timeout=10,
            verify=self._config.crewday.verify_tls,
        )

    def _headers(self) -> dict[str, str]:
        if not self._config.crewday.api_token:
            return {}
        return {"Authorization": f"Bearer {self._config.crewday.api_token}"}

    def _fetch_task_rows(
        self,
        client: httpx.Client,
        params: dict[str, str],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            request_params = dict(params)
            if cursor:
                request_params["cursor"] = cursor
            response = client.get(
                self._task_path(),
                params=request_params,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
            rows.extend(_rows(payload))
            if not isinstance(payload, dict) or not payload.get("has_more"):
                return rows
            next_cursor = payload.get("next_cursor")
            cursor = str(next_cursor) if next_cursor else None
            if cursor is None:
                return rows

    def _task_path(self) -> str:
        prefix = self._api_prefix()
        return f"{prefix}/tasks"

    def _task_detail_path(self, task_id: str) -> str:
        prefix = self._api_prefix()
        return f"{prefix}/tasks/{quote(task_id, safe='')}/detail"

    def _worker_paths(self) -> tuple[str, ...]:
        prefix = self._api_prefix()
        return (f"{prefix}/employees", f"{prefix}/users")

    def _api_prefix(self) -> str:
        if self._config.crewday.workspace_slug:
            slug = quote(self._config.crewday.workspace_slug, safe="")
            return f"/w/{slug}/api/v1"
        return "/api/v1"

    def _task_from_row(self, row: dict[str, Any], now: datetime) -> ReceiptTask:
        task_id = str(row.get("id", ""))
        detail = self._fetch_task_detail(task_id) if task_id else None
        return _task_from_crewday(row, now, detail=detail)

    def _fetch_task_detail(self, task_id: str) -> dict[str, Any] | None:
        try:
            with self._client() as client:
                response = client.get(
                    self._task_detail_path(task_id),
                    headers=self._headers(),
                )
                if response.status_code in {401, 403, 404}:
                    return None
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError, ValueError:
            return None
        return payload if isinstance(payload, dict) else None


def fetch_crewday_workers(config: AppConfig) -> tuple[CrewdayWorker, ...]:
    if config.crewday.source == "crewday_http":
        return CrewdayHttpTaskSource(config).fetch_workers()
    return tuple(
        CrewdayWorker(user_id=worker.crewday_user_id or worker.name, name=worker.name)
        for worker in config.workers
    )


def _task_from_crewday(
    row: dict[str, Any],
    now: datetime,
    *,
    detail: dict[str, Any] | None = None,
) -> ReceiptTask:
    task_row = row
    if isinstance(detail, dict) and isinstance(detail.get("task"), dict):
        task_row = {**row, **detail["task"]}

    scheduled = task_row.get("scheduled_for_utc") or task_row.get("scheduled_start")
    scheduled_dt = None
    if isinstance(scheduled, str):
        scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
        if scheduled_dt.tzinfo is not None and now.tzinfo is not None:
            scheduled_dt = scheduled_dt.astimezone(now.tzinfo)

    detail_checklist = detail.get("checklist") if isinstance(detail, dict) else None
    checklist_raw = (
        detail_checklist
        or task_row.get("checklist")
        or task_row.get("checklist_items")
        or []
    )
    checklist = tuple(
        str(item.get("label") or item.get("text") or item) for item in checklist_raw
    )
    property_payload = detail.get("property") if isinstance(detail, dict) else None
    property_name = task_row.get("property_name") or task_row.get("property")
    if isinstance(property_payload, dict):
        property_name = property_payload.get("name") or property_name
    return ReceiptTask(
        id=str(task_row.get("id", "")),
        title=str(task_row.get("title", "Untitled task")),
        property_name=property_name,
        area=task_row.get("area") or task_row.get("area_id"),
        scheduled_start=scheduled_dt,
        time_window=task_row.get("time_window_local"),
        duration_minutes=task_row.get("duration_minutes")
        or task_row.get("estimated_minutes"),
        priority=str(task_row.get("priority", "normal")),
        status=str(task_row.get("state") or task_row.get("status") or "pending"),
        photo_required=str(task_row.get("photo_evidence", "")).lower()
        in {"required", "require"},
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
