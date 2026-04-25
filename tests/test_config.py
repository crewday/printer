from __future__ import annotations

from pathlib import Path

from printer_app.config import ensure_config, load_config


def test_ensure_config_creates_yaml(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"

    assert ensure_config(path) is True
    assert path.exists()

    config = load_config(path)
    assert config.printer.profile == "epson_tm_t20ii"
    assert config.printer.code_page == "cp858"
    assert config.printer.image_logo is True
    assert config.printer.supports_print_density is True
    assert config.printer.supports_print_speed is True
    assert config.crewday.source == "mock"
    assert config.print_schedule.cron == ""
    assert config.workers[0].name == "Vincent"
    assert config.workers[0].schedule == ""


def test_load_config_reads_worker_timezone(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
  password_hash: null
crewday:
  source: mock
printer:
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
    timezone: Europe/Paris
    tasks:
      - Check arrivals
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.workers[0].timezone == "Europe/Paris"
    assert config.workers[0].tasks == ("Check arrivals",)


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
printer:
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
printer:
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
printer:
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

    assert config.printer.paper_columns == 48
    assert config.printer.code_page == "cp858"
    assert config.printer.cut is True


def test_config_can_override_profile_code_page(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"
    path.write_text(
        """
ui:
  username: admin
crewday:
  source: mock
printer:
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

    assert config.printer.code_page == "cp858"
