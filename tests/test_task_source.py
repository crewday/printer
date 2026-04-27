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
        def __init__(self, *, base_url: str, timeout: int) -> None:
            requested["base_url"] = base_url
            requested["timeout"] = timeout

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
        def __init__(self, *, base_url: str, timeout: int) -> None:
            requested["base_url"] = base_url
            requested["timeout"] = timeout

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
