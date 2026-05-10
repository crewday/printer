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
    assert config.crewday.verify_tls is True
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


def test_load_config_reads_crewday_http_tls_verification(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: crewday_http
  base_url: https://crewday.example
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
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.crewday.base_url == "https://crewday.example"
    assert config.crewday.verify_tls is False


def test_load_config_parses_string_booleans(tmp_path: Path) -> None:
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
      value: Hello
      bold: "false"
    - type: separator
      trailing_blank: "off"
    - type: tasks
printers:
  - name: Default
    type: network_escpos
    profile: epson_tm_t20ii
    host: 127.0.0.1
    port: 9100
    timeout_seconds: 5
    image_logo: "false"
    supports_print_density: "yes"
    supports_print_speed: "0"
    cut: "no"
workers:
  - name: Amina
    enabled: "on"
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.printers[0].image_logo is False
    assert config.printers[0].supports_print_density is True
    assert config.printers[0].supports_print_speed is False
    assert config.printers[0].cut is False
    assert config.workers[0].enabled is True
    assert config.receipt_template.sections[0].bold is False
    assert config.receipt_template.sections[1].trailing_blank is False


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


def test_load_config_usb_escpos_printer(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: USB Printer
    type: usb_escpos
    profile: epson_tm_t20ii
    usb_vendor_id: 0x04b8
    usb_product_id: 0x0e15
    timeout_seconds: 5
    paper_columns: 48
    code_page: cp1252
workers:
  - name: Amina
    enabled: true
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.printers[0].type == "usb_escpos"
    assert config.printers[0].usb_vendor_id == 0x04B8
    assert config.printers[0].usb_product_id == 0x0E15
    assert config.printers[0].host == ""
    assert config.printers[0].port == 0


def test_load_config_cups_escpos_printer(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: CUPS Printer
    type: cups_escpos
    profile: epson_tm_t20ii
    cups_printer_name: TM-T20II
    timeout_seconds: 10
    paper_columns: 48
    code_page: cp1252
workers:
  - name: Amina
    enabled: true
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.printers[0].type == "cups_escpos"
    assert config.printers[0].cups_printer_name == "TM-T20II"
    assert config.printers[0].timeout_seconds == 10


def test_load_config_rejects_usb_printer_without_vendor_id(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: Bad USB
    type: usb_escpos
    profile: epson_tm_t20ii
workers:
  - name: Amina
    enabled: true
""",
        encoding="utf-8",
    )

    try:
        load_config(path)
    except ValueError as exc:
        assert "usb_vendor_id" in str(exc)
    else:
        raise AssertionError("missing usb_vendor_id should fail config loading")


def test_load_config_rejects_cups_printer_without_name(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printers:
  - name: Bad CUPS
    type: cups_escpos
    profile: epson_tm_t20ii
workers:
  - name: Amina
    enabled: true
""",
        encoding="utf-8",
    )

    try:
        load_config(path)
    except ValueError as exc:
        assert "cups_printer_name" in str(exc)
    else:
        raise AssertionError("missing cups_printer_name should fail config loading")


def test_load_config_rejects_invalid_worker_schedule(tmp_path: Path) -> None:
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
    schedule: "0 8 *"
""",
        encoding="utf-8",
    )

    try:
        load_config(path)
    except ValueError as exc:
        assert "worker.schedule" in str(exc)
    else:
        raise AssertionError("invalid worker schedule should fail config loading")


def test_load_config_rejects_unknown_worker_printer(tmp_path: Path) -> None:
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
    printer: Missing
""",
        encoding="utf-8",
    )

    try:
        load_config(path)
    except ValueError as exc:
        assert "unknown printer" in str(exc)
    else:
        raise AssertionError("unknown worker printer should fail config loading")
