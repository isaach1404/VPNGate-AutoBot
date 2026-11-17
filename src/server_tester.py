
import socket
import subprocess
import base64
import platform
import tempfile
import time
import os
import re
import signal
import ipaddress
import urllib.request

from pathlib import Path


OPENVPN_TIMEOUT = 30

VPN_USERNAME = "vpn"
VPN_PASSWORD = "vpn"


def ping_server(ip, timeout=3):
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

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    except Exception as error:
        print(f"Ping error for {ip}: {error}")
        return False


def decode_openvpn_config(server):

    encoded = server.get(
        "OpenVPN_ConfigData_Base64", ""
    ).strip()

    if not encoded:
        return None

    try:
        return base64.b64decode(
            "".join(encoded.split()),
            validate=True
        ).decode("utf-8-sig")

    except Exception:
        return None


def extract_openvpn_details(server):

    config = decode_openvpn_config(server)

    if not config:
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

    if not 1 <= remote_port <= 65535:
        return None

    return {
        "host": remote_host,
        "port": remote_port,
        "protocol": protocol
    }


def check_tcp_port(host, port, timeout=3):

    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout
        ):
            return True

    except (OSError, TimeoutError):
        return False


def run_command(command, timeout=15):

    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True
        )

    except (subprocess.TimeoutExpired, OSError):
        return None


def get_public_ip():

    urls = [
        "https://api.ipify.org",
        "https://checkip.amazonaws.com"
    ]

    for url in urls:

        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "VPNGate-AutoBot/1.0"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=5
            ) as response:

                public_ip = response.read().decode(
                    "utf-8"
                ).strip()

            return str(ipaddress.ip_address(public_ip))

        except Exception:
            continue

    return None


def get_tunnel_public_ip(interface):

    result = run_command(
        [
            "sudo", "-n",
            "curl", "-s",
            "--max-time", "10",
            "--interface", interface,
            "https://api.ipify.org"
        ],
        timeout=15
    )

    if result is None or result.returncode != 0:
        return None

    value = result.stdout.strip()

    if not value or len(value) > 64 or " " in value:
        return None

    return value


def stop_openvpn(process):

    if process is None:
        return

    try:
        # Stop OpenVPN and all processes in its process group.
        os.killpg(process.pid, signal.SIGTERM)

    except ProcessLookupError:
        pass

    except Exception as error:
        print(f"OpenVPN termination warning: {error}")

        try:
            process.terminate()
        except Exception:
            pass

    try:
        process.wait(timeout=5)

    except subprocess.TimeoutExpired:

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            process.kill()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("WARNING: OpenVPN process did not stop.")

    # Ensure no child process remains in the same process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception:
        pass


def test_openvpn_connection(
    server,
    timeout=OPENVPN_TIMEOUT
):

    config = decode_openvpn_config(server)

    if not config:
        return {
            "status": "invalid_config",
            "public_ip_before": None,
            "public_ip_after": None
        }

    public_ip_before = get_public_ip()

    if not public_ip_before:
        return {
            "status": "baseline_ip_unavailable",
            "public_ip_before": None,
            "public_ip_after": None
        }

    process = None

    # Manage the temporary directory manually so that OpenVPN
    # is stopped before its configuration and credentials are removed.
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="vpngate_test_"
    )

    try:

        temp_path = Path(temporary_directory.name)

        config_path = temp_path / "server.ovpn"
        credentials_path = temp_path / "credentials.txt"
        log_path = temp_path / "openvpn.log"

        config_lines = []

        for line in config.splitlines():

            stripped = line.strip()

            if stripped.startswith("auth-user-pass"):
                continue

            if stripped.startswith("daemon"):
                continue

            if stripped.startswith("log "):
                continue

            # Keep the runner's own traffic on its normal route;
            # only the public-IP check endpoints go through the
            # tunnel. A full redirect would drop the CI connection.
            if stripped.startswith("redirect-gateway"):
                continue

            config_lines.append(line)

        credentials_path.write_text(
            f"{VPN_USERNAME}\n{VPN_PASSWORD}\n",
            encoding="utf-8"
        )

        os.chmod(credentials_path, 0o600)

        config_path.write_text(
            "\n".join(config_lines) + "\n",
            encoding="utf-8"
        )

        os.chmod(config_path, 0o600)

        device = f"vpngate{os.getpid() % 1000}"

        command = [
            "sudo",
            "-n",
            "openvpn",
            "--config",
            str(config_path),
            "--auth-user-pass",
            str(credentials_path),
            "--auth-nocache",
            "--dev",
            device,
            "--dev-type",
            "tun",
            "--connect-retry-max",
            "1",
            "--connect-timeout",
            "10",
            # The runner keeps its own default route; the tunnel is
            # only used for the interface-bound public-IP check.
            "--pull-filter",
            "ignore",
            "redirect-gateway",
            "--pull-filter",
            "ignore",
            "dhcp-option DNS",
            "--pull-filter",
            "ignore",
            "block-outside-dns",
            # VPN Gate configs pin legacy ciphers that OpenVPN 2.6+
            # refuses by default.
            "--data-ciphers",
            "AES-128-CBC:AES-256-CBC:AES-192-CBC:AES-128-GCM:AES-256-GCM:CHACHA20-POLY1305",
            "--data-ciphers-fallback",
            "AES-128-CBC",
            "--verb",
            "3"
        ]

        with log_path.open("w") as log_file:

            print(
                f"Starting real OpenVPN connection "
                f"to {server.get('IP', 'Unknown')}..."
            )

            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

            connected = False
            start_time = time.monotonic()

            while time.monotonic() - start_time < timeout:

                if process.poll() is not None:
                    break

                log_file.flush()

                log_content = log_path.read_text(
                    encoding="utf-8",
                    errors="replace"
                )

                if "Initialization Sequence Completed" in log_content:
                    connected = True
                    break

                time.sleep(1)

        if not connected:

            print(
                f"OpenVPN connection failed for "
                f"{server.get('IP', 'Unknown')}"
            )

            return {
                "status": "connection_failed",
                "public_ip_before": public_ip_before,
                "public_ip_after": None
            }

        print("OpenVPN tunnel established.")

        time.sleep(2)

        public_ip_after = None

        for _ in range(5):

            public_ip_after = get_tunnel_public_ip(device)

            if public_ip_after:
                break

            time.sleep(1)

        if not public_ip_after:

            return {
                "status": "public_ip_check_failed",
                "public_ip_before": public_ip_before,
                "public_ip_after": None
            }

        if public_ip_before != public_ip_after:

            print(
                f"Public IP changed: "
                f"{public_ip_before} -> {public_ip_after}"
            )

            return {
                "status": "connected",
                "public_ip_before": public_ip_before,
                "public_ip_after": public_ip_after
            }

        print(
            "VPN connection established, "
            "but public IP did not change."
        )

        return {
            "status": "ip_not_changed",
            "public_ip_before": public_ip_before,
            "public_ip_after": public_ip_after
        }

    except Exception as error:

        print(
            f"OpenVPN test error for "
            f"{server.get('IP', 'Unknown')}: {error}"
        )

        return {
            "status": "test_error",
            "public_ip_before": public_ip_before,
            "public_ip_after": None
        }

    finally:

        stop_openvpn(process)

        temporary_directory.cleanup()


def test_server(server):

    ip = server.get("IP", "").strip()

    result = {
        "ip": ip,
        "country": server.get("CountryLong", "Unknown"),
        "ping": False,
        "protocol": "unknown",
        "port": None,
        "port_status": "not_tested",
        "config_status": "invalid",
        "connection_status": "not_tested",
        "public_ip_before": None,
        "public_ip_after": None
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

    # UDP has no port to probe; the real connection test below is
    # the only meaningful check for those servers.
    if "tcp" in details["protocol"]:

        result["port_status"] = (
            "open"
            if check_tcp_port(
                details["host"],
                details["port"]
            )
            else "closed_or_blocked"
        )

        if result["port_status"] != "open":
            return result

    else:
        result["port_status"] = "not_tested_udp"

    connection_result = test_openvpn_connection(server)

    result["connection_status"] = connection_result["status"]

    result["public_ip_before"] = (
        connection_result["public_ip_before"]
    )

    result["public_ip_after"] = (
        connection_result["public_ip_after"]
    )

    return result
