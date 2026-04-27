from __future__ import annotations

from pathlib import Path

import yaml

from printer_app.config import config_to_raw, ensure_config, load_config


def test_ensure_config_creates_yaml(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"

    assert ensure_config(path) is True
    assert path.exists()

    config = load_config(path)
    assert config.printers[0].profile == "epson_tm_t20ii"
    assert config.printers[0].code_page == "cp858"
    assert config.printers[0].image_logo is True
    assert config.printers[0].supports_print_density is True
    assert config.printers[0].supports_print_speed is True
    assert config.crewday.source == "mock"
    assert config.crewday.workspace_slug is None
    assert config.print_schedule.cron == ""
    assert config.timezone == "Asia/Dubai"
    assert config.receipt_template.sections[0].type == "logo"
    assert config.receipt_template.sections[4].type == "tasks"
    assert config.workers[0].name == "Vincent"
    assert config.workers[0].schedule == ""
    assert config.workers[0].enabled is True


def test_load_config_reads_instance_timezone_and_worker_enabled(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
  password_hash: null
crewday:
  source: mock
timezone: Europe/Paris
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
    paper_columns: 48
    code_page: cp437
    image_logo: true
    supports_print_density: true
    supports_print_speed: true
    print_density: 8
    print_speed: 6
    cut: true
workers:
  - name: Amina
    schedule: "0 7 * * *"
    crewday_user_id: 01HXUSER
    enabled: false
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.timezone == "Europe/Paris"
    assert config.workers[0].enabled is False
    assert config.workers[0].crewday_user_id == "01HXUSER"


def test_load_config_reads_print_schedule(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
print_schedule:
  cron: "0 8 * * 1-5"
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.print_schedule.cron == "0 8 * * 1-5"


def test_load_config_reads_receipt_template(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
receipt_template:
  sections:
    - type: text
      value: "{{ brand }} / {{ worker_name }}"
      align: center
      bold: true
    - type: separator
      trailing_blank: false
    - type: tasks
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert len(config.receipt_template.sections) == 3
    assert (
        config.receipt_template.sections[0].value == "{{ brand }} / {{ worker_name }}"
    )
    assert config.receipt_template.sections[0].align == "center"
    assert config.receipt_template.sections[0].bold is True
    assert config.receipt_template.sections[1].trailing_blank is False

    raw = config_to_raw(config)
    assert raw["receipt_template"]["sections"][0]["align"] == "center"


def test_print_schedule_must_be_empty_or_five_field_cron(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
print_schedule:
  cron: "0 8 *"
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    try:
        load_config(path)
    except ValueError as exc:
        assert "print_schedule.cron" in str(exc)
    else:
        raise AssertionError("invalid cron should fail config loading")


def test_profile_defaults_fill_missing_capability_settings(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
workers:
  - name: Amina
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.printers[0].paper_columns == 48
    assert config.printers[0].code_page == "cp858"


def test_config_encrypts_stored_secrets_when_key_is_set(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PRINTER_CONFIG_SECRET_KEY", "test-secret-key")
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
  password_hash: pbkdf2_sha256$200000$salt$digest
crewday:
  source: crewday_http
  base_url: http://crewday:8000
  api_token: mip_key_secret
  workspace_slug: home
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
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    from printer_app.config import write_raw_config

    config = load_config(path)
    write_raw_config(path, config_to_raw(config))
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert stored["ui"]["username"].startswith("enc:v1:")
    assert stored["ui"]["password_hash"].startswith("enc:v1:")
    assert stored["crewday"]["api_token"].startswith("enc:v1:")
    assert load_config(path).ui.username == "admin"
    assert load_config(path).crewday.api_token == "mip_key_secret"
    assert load_config(path).crewday.workspace_slug == "home"
    assert config.printers[0].cut is True


def test_config_can_override_profile_code_page(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
    code_page: cp858
workers:
  - name: Amina
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.printers[0].code_page == "cp858"
