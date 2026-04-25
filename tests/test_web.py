from __future__ import annotations

from pathlib import Path

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
