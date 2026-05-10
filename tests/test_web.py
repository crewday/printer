from __future__ import annotations

from datetime import datetime
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
timezone: Asia/Dubai
printers:
  - name: Default
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
    crewday_user_id: user-1
    enabled: true
    printer: Default
  - name: Amina
    crewday_user_id: user-2
    enabled: true
    printer: Default
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
        "send_to_printer",
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


def test_ui_is_unprotected_when_no_password_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.delenv("PRINTER_UI_USERNAME", raising=False)
    monkeypatch.delenv("PRINTER_UI_PASSWORD", raising=False)

    client = TestClient(web.app)
    response = client.get("/")

    assert response.status_code == 200


def test_ui_requires_credentials_when_password_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.get("/")

    assert response.status_code == 401


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
        "send_to_printer",
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


def test_api_print_rejects_disabled_worker(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    stored["workers"][1]["enabled"] = False
    config_path.write_text(yaml.safe_dump(stored), encoding="utf-8")

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/receipts/print",
        json={"workers": ["Amina"]},
        auth=("admin", "admin"),
    )

    assert response.status_code == 404
    assert "disabled" in response.json()["detail"]


def test_worker_schedule_overrides_global_schedule(tmp_path: Path) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    stored["print_schedule"]["cron"] = "0 8 * * *"
    stored["workers"][1]["schedule"] = "30 9 * * *"
    config_path.write_text(yaml.safe_dump(stored), encoding="utf-8")

    from printer_app.config import load_config

    config = load_config(config_path)

    assert web._scheduled_worker_names(config, datetime(2026, 4, 26, 8, 0)) == [
        "Vincent"
    ]
    assert web._scheduled_worker_names(config, datetime(2026, 4, 26, 9, 30)) == [
        "Amina"
    ]


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
        "worker_enabled": ["0"],
        "worker_name": ["Vincent", "Amina", "Nora"],
        "worker_schedule": ["0 8 * * *", "", ""],
        "worker_crewday_user_id": ["user-1", "user-2", "user-3"],
        "worker_printer": ["Default", "Default", "Default"],
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
    assert [worker.name for worker in reloaded.workers] == [
        "Vincent",
        "Amina",
        "Nora",
    ]
    assert reloaded.workers[0].schedule == "0 8 * * *"
    assert reloaded.workers[0].crewday_user_id == "user-1"
    assert reloaded.workers[0].enabled is True
    assert reloaded.workers[1].enabled is False
    assert reloaded.workers[2].enabled is False


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
            "verify_tls": "on",
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
    assert stored["crewday"]["verify_tls"] is True
    assert stored["crewday"]["api_token"].startswith("enc:v1:")

    from printer_app.config import load_config

    reloaded = load_config(config_path)
    assert reloaded.crewday.api_token == "mip_key_secret"
    assert reloaded.crewday.workspace_slug == "villa-sud"
    assert reloaded.crewday.verify_tls is True


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
        "send_to_printer",
        lambda payload, printer: sent_payloads.append(payload),
    )

    client = TestClient(web.app)
    response = client.post(
        "/printer/Default/calibration/wizard",
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


def test_create_token_returns_full_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/tokens/create",
        json={"name": "Home Assistant", "scope": "print"},
        auth=("admin", "admin"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Home Assistant"
    assert body["scope"] == "print"
    assert body["token"].startswith("cpt_")
    assert body["token_prefix"].startswith("cpt_")
    assert body["created_at"] != ""
    assert len(body["token"]) == len("cpt_") + 64


def test_create_token_rejects_unknown_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/tokens/create",
        json={"name": "Reader", "scope": "read"},
        auth=("admin", "admin"),
    )

    assert response.status_code == 400
    assert "unsupported token scope" in response.json()["detail"]


def test_api_print_accepts_bearer_token(
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
        "send_to_printer",
        lambda payload, printer: sent_payloads.append(payload),
    )

    client = TestClient(web.app)
    create_resp = client.post(
        "/api/tokens/create",
        json={"name": "HA", "scope": "print"},
        auth=("admin", "admin"),
    )
    token = create_resp.json()["token"]

    print_resp = client.post(
        "/api/receipts/print",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert print_resp.status_code == 200
    assert print_resp.json()["count"] == 2
    assert len(sent_payloads) == 1


def test_api_print_rejects_invalid_bearer_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    response = client.post(
        "/api/receipts/print",
        headers={"Authorization": "Bearer cpt_invalid"},
    )

    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_revoke_token_removes_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    create_resp = client.post(
        "/api/tokens/create",
        json={"name": "HA", "scope": "print"},
        auth=("admin", "admin"),
    )
    prefix = create_resp.json()["token_prefix"]

    revoke_resp = client.post(
        f"/tokens/{prefix}/revoke",
        auth=("admin", "admin"),
        follow_redirects=False,
    )
    assert revoke_resp.status_code == 303

    list_resp = client.get("/api/tokens", auth=("admin", "admin"))
    assert all(t["token_prefix"] != prefix for t in list_resp.json())


def test_token_encrypts_hash_at_rest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)
    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")
    monkeypatch.setenv("PRINTER_CONFIG_SECRET_KEY", "test-secret-key")
    monkeypatch.setattr(
        web,
        "send_to_printer",
        lambda payload, printer: None,
    )

    client = TestClient(web.app)
    create_resp = client.post(
        "/api/tokens/create",
        json={"name": "HA", "scope": "print"},
        auth=("admin", "admin"),
    )
    token = create_resp.json()["token"]

    stored = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert stored["api_tokens"][0]["token_hash"].startswith("enc:v1:")

    from printer_app.config import load_config

    reloaded = load_config(config_path)
    assert len(reloaded.api_tokens) == 1
    assert reloaded.api_tokens[0].name == "HA"

    print_resp = client.post(
        "/api/receipts/print",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert print_resp.status_code == 200


def test_token_scope_restricts_to_print_endpoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "printer.yaml"
    _write_config(config_path)

    monkeypatch.setenv("PRINTER_CONFIG", str(config_path))
    monkeypatch.setenv("PRINTER_UI_PASSWORD", "admin")

    client = TestClient(web.app)
    create_resp = client.post(
        "/api/tokens/create",
        json={"name": "HA", "scope": "print"},
        auth=("admin", "admin"),
    )
    token = create_resp.json()["token"]

    template_resp = client.get(
        "/api/template/default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert template_resp.status_code == 401
