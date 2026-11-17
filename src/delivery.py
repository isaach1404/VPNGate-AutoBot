
"""Shared file lookup and report rows for every messenger."""

import json
import re

from pathlib import Path


OPENVPN_FILE = Path("output/selected_servers.json")
SSTP_FILE = Path("output/selected_sstp_servers.json")
OPENVPN_DIR = Path("output/openvpn")


def load_servers(path, required=True):

    if not path.exists():

        if required:
            raise FileNotFoundError(
                f"Server list not found: {path}"
            )

        print(f"WARNING: server list missing: {path}")
        return []

    with path.open("r", encoding="utf-8") as file:
        servers = json.load(file)

    if not isinstance(servers, list):
        raise ValueError(f"Invalid server list: {path}")

    return servers


def config_filename(country_code, ip, hostname):
    """Unique per server.

    Distinct VPN Gate servers can share one IP, so the hostname is
    part of the name; without it two servers would overwrite each
    other's file and only one would ever be delivered.
    """

    parts = [
        str(country_code).strip() or "Unknown",
        str(ip).strip() or "Unknown",
        str(hostname).strip()
    ]

    name = "_".join(part for part in parts if part)

    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", "_", name)

    return f"{name[:90]}.ovpn"


def find_config(server):
    """Locate the generated .ovpn file for a selected server."""

    if not str(server.get("ip", "")).strip():
        return None

    candidate = OPENVPN_DIR / config_filename(
        server.get("country_code", ""),
        server.get("ip", ""),
        server.get("hostname", "")
    )

    return candidate if candidate.exists() else None


def openvpn_rows(servers):
    """The fields the VPN Gate site itself shows for each server."""

    for index, server in enumerate(servers, start=1):

        sessions = server.get("sessions")

        yield {
            "index": index,
            "country": str(server.get("country", "Unknown")),
            "ip": str(server.get("ip", "?")),
            "protocol": str(
                server.get("protocol", "?")
            ).upper(),
            "port": server.get("port", "?"),
            "days": server.get("uptime_days"),
            "sessions": sessions,
            "session_label": (
                "session" if sessions == 1 else "sessions"
            )
        }


def sstp_rows(servers):
    """Hostname, destination details, and any non-default login."""

    for index, server in enumerate(servers, start=1):

        port = server.get("sstp_port", 443)

        username = str(server.get("username", "vpn"))
        password = str(server.get("password", "vpn"))

        custom_login = (
            username != "vpn" or password != "vpn"
        )

        sessions = server.get("sessions")

        yield {
            "index": index,
            "hostname": str(
                server.get("sstp_hostname", "Unknown")
            ),
            "country": str(server.get("country", "")).strip(),
            "ip": str(server.get("ip", "")).strip(),
            "days": server.get("uptime_days"),
            "sessions": sessions,
            "session_label": (
                "session" if sessions == 1 else "sessions"
            ),
            "port": port if port != 443 else None,
            "username": username if custom_login else None,
            "password": password if custom_login else None
        }


def encode_multipart(fields, files):
    """Build a multipart body without a third-party dependency."""

    import uuid

    boundary = uuid.uuid4().hex
    lines = []

    for name, value in fields.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; '
                f'name="{name}"'
            ).encode()
        )
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for name, (filename, content) in files.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; '
                f'name="{name}"; filename="{filename}"'
            ).encode()
        )
        lines.append(b"Content-Type: application/octet-stream")
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")

    return (
        b"\r\n".join(lines),
        f"multipart/form-data; boundary={boundary}"
    )
