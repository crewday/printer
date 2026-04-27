from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from printer_app.models import PrinterConfig
from printer_app.transport import (
    printer_connection_label,
    send_to_printer,
)


def _network_printer(**overrides) -> PrinterConfig:
    defaults = dict(
        name="Test",
        type="network_escpos",
        profile="epson_tm_t20ii",
        host="192.168.20.15",
        port=9100,
        timeout_seconds=5.0,
        paper_columns=48,
        code_page="cp1252",
        image_logo=True,
        supports_print_density=True,
        supports_print_speed=True,
        print_density=8,
        print_speed=6,
        cut=True,
    )
    defaults.update(overrides)
    return PrinterConfig(**defaults)


def _usb_printer(**overrides) -> PrinterConfig:
    return _network_printer(
        type="usb_escpos",
        host="",
        port=0,
        usb_vendor_id=0x04B8,
        usb_product_id=0x0E15,
        **overrides,
    )


def _cups_printer(**overrides) -> PrinterConfig:
    return _network_printer(
        type="cups_escpos",
        host="",
        port=0,
        cups_printer_name="TM-T20II",
        **overrides,
    )


def test_send_to_printer_rejects_unknown_type() -> None:
    printer = _network_printer(type="bluetooth_escpos")
    with pytest.raises(ValueError, match="unsupported printer type"):
        send_to_printer(b"\x00", printer)


def test_send_to_printer_dispatches_network() -> None:
    printer = _network_printer()
    with patch("printer_app.transport._send_network") as mock_send:
        send_to_printer(b"\x1b@", printer)
        mock_send.assert_called_once_with(b"\x1b@", printer)


def test_send_to_printer_dispatches_usb() -> None:
    printer = _usb_printer()
    with patch("printer_app.transport._send_usb") as mock_send:
        send_to_printer(b"\x1b@", printer)
        mock_send.assert_called_once_with(b"\x1b@", printer)


def test_send_to_printer_dispatches_cups() -> None:
    printer = _cups_printer()
    with patch("printer_app.transport._send_cups") as mock_send:
        send_to_printer(b"\x1b@", printer)
        mock_send.assert_called_once_with(b"\x1b@", printer)


def test_usb_send_finds_device_and_writes() -> None:
    printer = _usb_printer()
    mock_dev = MagicMock()
    mock_dev.is_kernel_driver_active.return_value = False
    mock_cfg = MagicMock()
    mock_dev.get_active_configuration.return_value = mock_cfg
    mock_intf = MagicMock()
    mock_cfg.__getitem__ = lambda self, key: mock_intf
    mock_ep = MagicMock()
    mock_usb = MagicMock()
    mock_usb.core.find.return_value = mock_dev
    mock_usb.util.find_descriptor.return_value = mock_ep
    mock_usb.util.endpoint_direction = lambda x: x
    mock_usb.util.ENDPOINT_OUT = 1
    usb_modules = {
        "usb": mock_usb,
        "usb.core": mock_usb.core,
        "usb.util": mock_usb.util,
    }
    with patch.dict("sys.modules", usb_modules):
        from printer_app.transport import _send_usb

        _send_usb(b"\x1b@", printer)
        mock_usb.core.find.assert_called_once_with(
            idVendor=0x04B8, idProduct=0x0E15
        )
        mock_ep.write.assert_called_once_with(b"\x1b@")


def test_usb_send_raises_when_device_not_found() -> None:
    printer = _usb_printer()
    mock_usb = MagicMock()
    mock_usb.core.find.return_value = None
    usb_modules = {
        "usb": mock_usb,
        "usb.core": mock_usb.core,
        "usb.util": mock_usb.util,
    }
    with patch.dict("sys.modules", usb_modules):
        from printer_app.transport import _send_usb

        with pytest.raises(ConnectionError, match="no USB device found"):
            _send_usb(b"\x1b@", printer)


def test_cups_send_calls_lp_command() -> None:
    printer = _cups_printer()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        from printer_app.transport import _send_cups

        _send_cups(b"\x1b@", printer)
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0] == [
            "lp", "-d", "TM-T20II", "-o", "raw",
        ]
        assert args[1]["input"] == b"\x1b@"


def test_cups_send_raises_on_lp_failure() -> None:
    printer = _cups_printer()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stderr=b"printer not found"
        )
        from printer_app.transport import _send_cups

        with pytest.raises(ConnectionError, match="CUPS lp failed"):
            _send_cups(b"\x1b@", printer)


def test_cups_send_raises_when_lp_not_found() -> None:
    printer = _cups_printer()
    with patch(
        "subprocess.run", side_effect=FileNotFoundError("lp not found")
    ):
        from printer_app.transport import _send_cups

        with pytest.raises(ConnectionError, match="lp command not found"):
            _send_cups(b"\x1b@", printer)


def test_cups_send_raises_on_timeout() -> None:
    printer = _cups_printer()
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired("lp", 5),
    ):
        from printer_app.transport import _send_cups

        with pytest.raises(ConnectionError, match="timed out"):
            _send_cups(b"\x1b@", printer)


def test_connection_label_network() -> None:
    printer = _network_printer()
    assert printer_connection_label(printer) == "192.168.20.15:9100"


def test_connection_label_usb() -> None:
    printer = _usb_printer()
    assert printer_connection_label(printer) == "USB 0x04b8:0x0e15"


def test_connection_label_cups() -> None:
    printer = _cups_printer()
    assert printer_connection_label(printer) == "CUPS:TM-T20II"
