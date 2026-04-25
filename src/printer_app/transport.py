from __future__ import annotations

import socket

from printer_app.models import PrinterConfig


def send_to_network_printer(payload: bytes, printer: PrinterConfig) -> None:
    if printer.type != "network_escpos":
        raise ValueError(f"unsupported printer type: {printer.type}")

    try:
        with socket.create_connection(
            (printer.host, printer.port),
            timeout=printer.timeout_seconds,
        ) as sock:
            sock.sendall(payload)
    except OSError as exc:
        raise ConnectionError(
            f"could not reach printer at {printer.host}:{printer.port}: {exc}"
        ) from exc
