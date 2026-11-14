
import socket
import subprocess
import base64
import re
import platform


def ping_server(ip, timeout=3):
    """
    Check whether the server responds to ICMP ping.
    """

    try:
        if platform.system().lower() == "windows":
            command = [
                "ping", "-n", "1",
                "-w", str(timeout * 1000), ip
            ]
        else:
            command = [
                "ping", "-c", "1",
                "-W", str(timeout), ip
            ]

        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
            check=False
        )

        return result.returncode == 0

    except FileNotFoundError:
        print("WARNING: Ping command is not available.")
        return False

    except subprocess.TimeoutExpired:
        return False

    except Exception as error:
        print(f"Ping error for {ip}: {error}")
        return False


def extract_openvpn_details(server):
    """
    Extract remote host, port and protocol
    from the OpenVPN configuration.
    """

    encoded = server.get(
        "OpenVPN_ConfigData_Base64", ""
    ).strip()

    if not encoded:
        return None

    try:
        config = base64.b64decode(
            "".join(encoded.split()),
            validate=True
        ).decode("utf-8-sig")

    except Exception:
        return None

    protocol = "udp"

    remote_host = None
    remote_port = None

    for line in config.splitlines():

        line = line.strip()

        if not line or line.startswith("#") or line.startswith(";"):
            continue

        parts = line.split()

        if parts[0] == "proto" and len(parts) > 1:
            protocol = parts[1].lower()

        if parts[0] == "remote" and len(parts) >= 3:
            remote_host = parts[1]
            remote_port = parts[2]

            if len(parts) >= 4:
                protocol = parts[3].lower()

            break

    if not remote_host or not remote_port:
        return None

    try:
        remote_port = int(remote_port)
    except ValueError:
        return None

    return {
        "host": remote_host,
        "port": remote_port,
        "protocol": protocol
    }


def check_tcp_port(host, port, timeout=3):
    """
    Check whether a TCP port accepts connections.
    """

    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout
        ):
            return True

    except (OSError, TimeoutError):
        return False


def test_server(server):
    """
    Perform preliminary network checks.
    """

    ip = server.get("IP", "").strip()

    result = {
        "ip": ip,
        "country": server.get("CountryLong", "Unknown"),
        "ping": False,
        "protocol": "unknown",
        "port": None,
        "port_status": "not_tested",
        "config_status": "invalid"
    }

    if not ip:
        return result

    result["ping"] = ping_server(ip)

    details = extract_openvpn_details(server)

    if details is None:
        return result

    result["config_status"] = "valid"
    result["protocol"] = details["protocol"]
    result["port"] = details["port"]

    if "tcp" in details["protocol"]:
        result["port_status"] = (
            "open"
            if check_tcp_port(
                details["host"],
                details["port"]
            )
            else "closed_or_blocked"
        )

    elif "udp" in details["protocol"]:
        result["port_status"] = "not_tested_udp"

    return result
