from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from printer_app.config import load_config
from printer_app.task_source import CrewdayHttpTaskSource


def test_crewday_http_source_uses_workspace_scoped_task_route(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: http://crewday:8000
  api_token: mip_key_secret
  workspace_slug: villa-sud
  verify_tls: false
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    crewday_user_id: 01HXUSER
    enabled: true
""",
        encoding="utf-8",
    )
    requested: dict[str, object] = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": []}

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            requested["base_url"] = base_url
            requested["timeout"] = timeout
            requested["verify"] = verify

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            path: str,
            *,
            params: dict[str, str],
            headers: dict[str, str],
        ) -> Response:
            requested["path"] = path
            requested["params"] = params
            requested["headers"] = headers
            return Response()

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)

    config = load_config(path)
    batch = CrewdayHttpTaskSource(config).fetch_task_batch(
        config.workers[0],
        now=datetime(2026, 4, 26, 9, 0, tzinfo=ZoneInfo("Asia/Dubai")),
    )

    assert batch.tasks == ()
    assert requested["path"] == "/w/villa-sud/api/v1/tasks"
    assert requested["headers"] == {"Authorization": "Bearer mip_key_secret"}
    assert requested["params"]["assignee_user_id"] == "01HXUSER"
    assert requested["verify"] is False


def test_crewday_http_source_queries_configured_local_day_and_localizes_times(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: http://crewday:8000
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    crewday_user_id: 01HXUSER
    enabled: true
""",
        encoding="utf-8",
    )
    requests: list[dict[str, object]] = []

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "id": "task-1",
                        "title": "Morning check",
                        "scheduled_for_utc": "2026-04-25T22:30:00Z",
                    }
                ]
            }

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            self.base_url = base_url
            self.timeout = timeout
            self.verify = verify

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str],
        ) -> Response:
            requests.append(
                {
                    "base_url": self.base_url,
                    "timeout": self.timeout,
                    "verify": self.verify,
                    "path": path,
                    "params": params or {},
                    "headers": headers,
                }
            )
            return Response()

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)

    config = load_config(path)
    batch = CrewdayHttpTaskSource(config).fetch_task_batch(
        config.workers[0],
        now=datetime(2026, 4, 26, 1, 0, tzinfo=ZoneInfo("Asia/Dubai")),
    )

    task_request = requests[0]
    assert (
        task_request["params"]["scheduled_for_utc_gte"] == "2026-04-25T20:00:00+00:00"
    )
    assert task_request["params"]["scheduled_for_utc_lt"] == "2026-04-26T20:00:00+00:00"
    assert requests[1]["path"] == "/api/v1/tasks/task-1/detail"
    assert batch.tasks[0].scheduled_start is not None
    assert batch.tasks[0].scheduled_start.strftime("%H:%M") == "02:30"


def test_crewday_http_source_fetches_workspace_worker_roster(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: http://crewday:8000
  api_token: mip_key_secret
  workspace_slug: villa-sud
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Existing
    crewday_user_id: 01HXEXISTING
""",
        encoding="utf-8",
    )
    requested: dict[str, object] = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, str]]:
            return [{"id": "01HXUSER", "name": "Amina"}]

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            requested["base_url"] = base_url
            requested["timeout"] = timeout
            requested["verify"] = verify

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, path: str, *, headers: dict[str, str]) -> Response:
            requested["path"] = path
            requested["headers"] = headers
            return Response()

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)

    workers = CrewdayHttpTaskSource(load_config(path)).fetch_workers()

    assert workers[0].user_id == "01HXUSER"
    assert workers[0].name == "Amina"
    assert requested["path"] == "/w/villa-sud/api/v1/employees"
    assert requested["headers"] == {"Authorization": "Bearer mip_key_secret"}


def test_crewday_http_source_enriches_tasks_with_detail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: https://crewday.example
  api_token: mip_key_secret
  workspace_slug: villa-sud
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    crewday_user_id: 01HXUSER
""",
        encoding="utf-8",
    )

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            return None

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str],
        ) -> Response:
            if path.endswith("/detail"):
                return Response(
                    {
                        "task": {
                            "id": "task-1",
                            "title": "Morning check",
                            "time_window_local": "08:00-08:30",
                        },
                        "property": {"name": "Villa Sud"},
                        "checklist": [{"label": "Open shutters"}],
                    }
                )
            return Response(
                {
                    "data": [
                        {
                            "id": "task-1",
                            "title": "Morning check",
                            "scheduled_for_utc": "2026-04-26T04:00:00Z",
                            "photo_evidence": "required",
                        }
                    ]
                }
            )

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)

    batch = CrewdayHttpTaskSource(load_config(path)).fetch_task_batch(
        load_config(path).workers[0],
        now=datetime(2026, 4, 26, 8, 0, tzinfo=ZoneInfo("Asia/Dubai")),
    )

    assert batch.tasks[0].property_name == "Villa Sud"
    assert batch.tasks[0].time_window == "08:00-08:30"
    assert batch.tasks[0].photo_required is True
    assert batch.tasks[0].checklist == ("Open shutters",)


def test_crewday_http_source_allows_visible_tasks_without_worker_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: http://crewday:8000
  workspace_slug: villa-sud
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Token subject
    crewday_user_id: null
""",
        encoding="utf-8",
    )
    requested: dict[str, object] = {}

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": []}

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            return None

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(
            self,
            path: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str],
        ) -> Response:
            requested["params"] = params or {}
            return Response()

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)
    config = load_config(path)

    CrewdayHttpTaskSource(config).fetch_task_batch(
        config.workers[0],
        now=datetime(2026, 4, 26, 8, 0, tzinfo=ZoneInfo("Asia/Dubai")),
    )

    assert "assignee_user_id" not in requested["params"]


def test_crewday_http_source_worker_roster_falls_back_when_forbidden(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: http://crewday:8000
  workspace_slug: villa-sud
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    crewday_user_id: 01HXUSER
""",
        encoding="utf-8",
    )

    class Response:
        status_code = 403

        def raise_for_status(self) -> None:
            raise AssertionError("403 roster lookup should not raise")

    class Client:
        def __init__(self, *, base_url: str, timeout: int, verify: bool) -> None:
            return None

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, path: str, *, headers: dict[str, str]) -> Response:
            return Response()

    import printer_app.task_source as task_source

    monkeypatch.setattr(task_source.httpx, "Client", Client)

    assert CrewdayHttpTaskSource(load_config(path)).fetch_workers() == ()
