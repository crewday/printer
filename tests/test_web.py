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
