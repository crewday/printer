from __future__ import annotations

import socket
import subprocess

from printer_app.models import PrinterConfig

SUPPORTED_TYPES = ("network_escpos", "usb_escpos", "cups_escpos")


def send_to_printer(payload: bytes, printer: PrinterConfig) -> None:
    if printer.type == "network_escpos":
        _send_network(payload, printer)
    elif printer.type == "usb_escpos":
        _send_usb(payload, printer)
    elif printer.type == "cups_escpos":
        _send_cups(payload, printer)
    else:
        raise ValueError(f"unsupported printer type: {printer.type}")


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
    detached = False
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
            detached = True
        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
            ),
        )
        if ep_out is None:
            raise ConnectionError("no OUT endpoint found on USB printer device")
        offset = 0
        while offset < len(payload):
            written = ep_out.write(payload[offset:])
            offset += written
    except usb.core.USBError as exc:
        raise ConnectionError(f"USB write failed: {exc}") from exc
    finally:
        usb.util.dispose_resources(dev)
        if detached:
            try:
                usb.util.dispose_resources(dev)
                dev.attach_kernel_driver(0)
            except usb.core.USBError, Exception:
                pass


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


def discover_usb_devices() -> list[dict[str, object]]:
    try:
        import usb.core
    except Exception:
        return []
    try:
        devices = usb.core.find(find_all=True)
        results: list[dict[str, object]] = []
        for dev in devices:
            if not any(
                iface.bInterfaceClass == 7
                for cfg in dev
                for iface in cfg
            ):
                continue
            try:
                manufacturer = usb.core.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
            except Exception:
                manufacturer = ""
            try:
                product = usb.core.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
            except Exception:
                product = ""
            parts = [p for p in (manufacturer, product) if p]
            description = " ".join(parts) or f"USB device 0x{dev.idVendor:04x}:0x{dev.idProduct:04x}"
            results.append({
                "vendor_id": dev.idVendor,
                "product_id": dev.idProduct,
                "description": description,
            })
        return results
    except Exception:
        return []


def discover_cups_printers() -> list[dict[str, object]]:
    try:
        result = subprocess.run(
            ["lpstat", "-p", "-d"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    printers: list[dict[str, object]] = []
    default_name: str | None = None
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line.startswith("printer"):
            parts = line.split()
            if len(parts) >= 2:
                name = parts[1]
                status = " ".join(parts[3:]) if len(parts) > 3 else "idle"
                printers.append({"name": name, "status": status, "is_default": False})
        elif line.startswith("system default destination:"):
            default_name = line.split(":")[-1].strip()
    if default_name:
        for p in printers:
            if p["name"] == default_name:
                p["is_default"] = True
    return printers


def printer_connection_label(printer: PrinterConfig) -> str:
    if printer.type == "network_escpos":
        return f"{printer.host}:{printer.port}"
    if printer.type == "usb_escpos":
        return f"USB 0x{printer.usb_vendor_id:04x}:0x{printer.usb_product_id:04x}"
    if printer.type == "cups_escpos":
        return f"CUPS:{printer.cups_printer_name}"
    return printer.type
