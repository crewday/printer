from __future__ import annotations

import socket
import subprocess

from printer_app.models import PrinterConfig

SUPPORTED_TYPES = ("network_escpos", "usb_escpos", "cups_escpos")


def send_to_printer(payload: bytes, printer: PrinterConfig) -> None:
    if printer.type not in SUPPORTED_TYPES:
        raise ValueError(f"unsupported printer type: {printer.type}")
    dispatch = {
        "network_escpos": _send_network,
        "usb_escpos": _send_usb,
        "cups_escpos": _send_cups,
    }
    dispatch[printer.type](payload, printer)


def _send_network(payload: bytes, printer: PrinterConfig) -> None:
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


def _send_usb(payload: bytes, printer: PrinterConfig) -> None:
    import usb.core
    import usb.util

    dev = usb.core.find(
        idVendor=printer.usb_vendor_id,
        idProduct=printer.usb_product_id,
    )
    if dev is None:
        raise ConnectionError(
            f"no USB device found with vendor=0x{printer.usb_vendor_id:04x} "
            f"product=0x{printer.usb_product_id:04x}"
        )
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        if ep_out is None:
            raise ConnectionError("no OUT endpoint found on USB printer device")
        ep_out.write(payload)
    except usb.core.USBError as exc:
        raise ConnectionError(f"USB write failed: {exc}") from exc
    finally:
        usb.util.dispose_resources(dev)


def _send_cups(payload: bytes, printer: PrinterConfig) -> None:
    try:
        result = subprocess.run(
            [
                "lp",
                "-d",
                printer.cups_printer_name,
                "-o",
                "raw",
            ],
            input=payload,
            capture_output=True,
            timeout=printer.timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise ConnectionError(
            "lp command not found; install cups-client package"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError(
            f"CUPS lp timed out for printer {printer.cups_printer_name!r}"
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise ConnectionError(
            f"CUPS lp failed for printer {printer.cups_printer_name!r}: {stderr}"
        )


def printer_connection_label(printer: PrinterConfig) -> str:
    if printer.type == "network_escpos":
        return f"{printer.host}:{printer.port}"
    if printer.type == "usb_escpos":
        return f"USB 0x{printer.usb_vendor_id:04x}:0x{printer.usb_product_id:04x}"
    if printer.type == "cups_escpos":
        return f"CUPS:{printer.cups_printer_name}"
    return printer.type
