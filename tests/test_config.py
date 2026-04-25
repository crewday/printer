from __future__ import annotations

from pathlib import Path

from printer_app.config import ensure_config, load_config


def test_ensure_config_creates_yaml(tmp_path: Path) -> None:
    path = tmp_path / "printer.yaml"

    assert ensure_config(path) is True
    assert path.exists()

    config = load_config(path)
    assert config.printer.profile == "epson_tm_t20ii"
    assert config.crewday.source == "mock"
    assert config.workers[0].name == "Vincent"


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
