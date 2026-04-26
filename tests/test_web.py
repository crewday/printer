from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import yaml
from fastapi.testclient import TestClient

from printer_app import web


def _write_config(path: Path) -> None:
    path.write_text(
        """
ui:
  username: admin
  password_hash: null
crewday:
  source: mock
print_schedule:
  cron: ""
printer:
  type: network_escpos
  profile: epson_tm_t20ii
  host: 127.0.0.1
  port: 9100
  timeout_seconds: 5
  paper_columns: 48
  code_page: cp858
  image_logo: true
  supports_print_density: true
  supports_print_speed: true
  print_density: 8
  print_speed: 6
  cut: false
workers:
  - name: Vincent
    timezone: Asia/Dubai
    tasks:
      - Prepare Villa Sud
  - name: Amina
    timezone: Europe/Paris
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )


def test_api_prints_all_workers_by_default_with_cuts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    sent_payloads: list[bytes] = []

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setattr(
        web,
        "send_to_network_printer",
        lambda payload, printer: sent_payloads.append(payload),
    )

    client = TestClient(web.app)
    response = client.post(
        "/api/receipts/print",
        auth=("admin", "admin"),
    )

    assert response.status_code == 200
    assert response.json()["workers"] == ["Vincent", "Amina"]
    assert response.json()["count"] == 2
    assert response.json()["cut"] is True
    assert len(sent_payloads) == 1
    assert sent_payloads[0].count(b"\x1dVA\x03") == 2
    assert b"Vincent" in sent_payloads[0]
    assert b"Amina" in sent_payloads[0]


def test_api_prints_requested_workers_from_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    sent_payloads: list[bytes] = []

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setattr(
        web,
        "send_to_network_printer",
        lambda payload, printer: sent_payloads.append(payload),
    )

    client = TestClient(web.app)
    response = client.post(
        "/api/receipts/print",
        json={"workers": ["Amina"]},
        auth=("admin", "admin"),
    )

    assert response.status_code == 200
    assert response.json()["workers"] == ["Amina"]
    assert sent_payloads[0].count(b"\x1dVA\x03") == 1
    assert b"Amina" in sent_payloads[0]
    assert b"Vincent" not in sent_payloads[0]


def test_api_print_rejects_unknown_worker(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/receipts/print",
        json={"workers": ["Missing"]},
        auth=("admin", "admin"),
    )

    assert response.status_code == 404
    assert "Missing" in response.json()["detail"]


def test_template_default_returns_bundled_sections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.get("/api/template/default", auth=("admin", "admin"))

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert any(s["type"] == "tasks" for s in sections)
    assert all("underline" in s for s in sections)


def test_template_preview_returns_png(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/template/preview",
        json={
            "sections": [
                {
                    "type": "text",
                    "value": "Hello {{ worker_name }}",
                    "align": "center",
                    "bold": True,
                    "underline": 1,
                },
                {"type": "separator"},
                {"type": "tasks"},
            ]
        },
        auth=("admin", "admin"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["src"].startswith("data:image/png;base64,")
    assert body["width_dots"] > 0
    assert body["height_dots"] > 0


def test_template_preview_rejects_invalid_underline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/template/preview",
        json={"sections": [{"type": "text", "value": "x", "underline": 3}]},
        auth=("admin", "admin"),
    )

    assert response.status_code == 400
    assert "underline" in response.json()["detail"]


def test_template_save_round_trips_to_yaml(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/template/save",
        json={
            "sections": [
                {
                    "type": "text",
                    "value": "Saved layout",
                    "align": "right",
                    "underline": 2,
                },
                {"type": "tasks"},
            ]
        },
        auth=("admin", "admin"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"

    from printer_app.config import load_config

    reloaded = load_config(config_path)
    assert len(reloaded.receipt_template.sections) == 2
    assert reloaded.receipt_template.sections[0].value == "Saved layout"
    assert reloaded.receipt_template.sections[0].align == "right"
    assert reloaded.receipt_template.sections[0].underline == 2
    assert reloaded.receipt_template.sections[1].type == "tasks"


def test_save_workers_round_trips_to_yaml(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    form = {
        "worker_enabled": ["0", "2"],
        "worker_name": ["Vincent", "Amina", "Nora"],
        "worker_timezone": ["Asia/Dubai", "Europe/Paris", "Europe/Paris"],
        "worker_schedule": ["0 8 * * *", "", ""],
        "worker_crewday_user_id": ["user-1", "", ""],
        "worker_tasks": ["Open house\nCheck stock", "Skipped", "Prep cart"],
    }
    response = client.post(
        "/workers",
        content=urlencode(form, doseq=True),
        headers={"content-type": "application/x-www-form-urlencoded"},
        auth=("admin", "admin"),
        follow_redirects=False,
    )

    assert response.status_code == 303

    from printer_app.config import load_config

    reloaded = load_config(config_path)
    assert [worker.name for worker in reloaded.workers] == ["Vincent", "Nora"]
    assert reloaded.workers[0].schedule == "0 8 * * *"
    assert reloaded.workers[0].crewday_user_id == "user-1"
    assert reloaded.workers[0].tasks == ("Open house", "Check stock")
    assert reloaded.workers[1].timezone == "Europe/Paris"
    assert reloaded.workers[1].tasks == ("Prep cart",)


def test_save_crewday_persists_workspace_slug_and_encrypted_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setenv("PRINTER_CONFIG_SECRET_KEY", "test-secret-key")

    client = TestClient(web.app)
    response = client.post(
        "/crewday",
        data={
            "source": "crewday_http",
            "base_url": "http://crewday:8000/",
            "workspace_slug": "villa-sud",
            "api_token": "mip_key_secret",
        },
        auth=("admin", "admin"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["crewday"]["source"] == "crewday_http"
    assert stored["crewday"]["base_url"] == "http://crewday:8000"
    assert stored["crewday"]["workspace_slug"] == "villa-sud"
    assert stored["crewday"]["api_token"].startswith("enc:v1:")

    from printer_app.config import load_config

    reloaded = load_config(config_path)
    assert reloaded.crewday.api_token == "mip_key_secret"
    assert reloaded.crewday.workspace_slug == "villa-sud"


def test_save_access_encrypts_configured_login(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setenv("PRINTER_CONFIG_SECRET_KEY", "test-secret-key")

    client = TestClient(web.app)
    response = client.post(
        "/access",
        data={"ui_username": "operator", "ui_password": "new-password"},
        auth=("admin", "admin"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["ui"]["username"].startswith("enc:v1:")
    assert stored["ui"]["password_hash"].startswith("enc:v1:")

    from printer_app.auth import verify_password
    from printer_app.config import load_config

    monkeypatch.delenv("PRINTER_UI_PASSWORD")
    monkeypatch.delenv("PRINTER_UI_USERNAME")
    reloaded = load_config(config_path)
    assert reloaded.ui.username == "operator"
    assert reloaded.ui.password_hash is not None
    assert verify_password("new-password", reloaded.ui.password_hash)


def test_calibration_wizard_prints_compact_batch_with_one_cut_at_end(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    sent_payloads: list[bytes] = []

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setattr(
        web,
        "send_to_network_printer",
        lambda payload, printer: sent_payloads.append(payload),
    )

    client = TestClient(web.app)
    response = client.post(
        "/calibration/wizard",
        data={"phase": "quick", "density": "8", "speed": "6"},
        auth=("admin", "admin"),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload.count(b"density=") == 4
    assert b"density=4 speed=12" in payload
    assert b"density=10 speed=4" in payload
    assert payload.count(b"\x1dVA\x03") == 1
    assert payload.endswith(b"\x1dVA\x03")
