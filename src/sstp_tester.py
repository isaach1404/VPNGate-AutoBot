
import json
import os
import signal
import subprocess
import time
import urllib.request

from pathlib import Path
from tempfile import TemporaryDirectory


INPUT_FILE = "output/sstp_servers.json"
OUTPUT_FILE = "output/selected_sstp_servers.json"

TARGET_SERVERS = 10
MAX_SERVERS_TO_TEST = 20
CONNECTION_TIMEOUT = 30

# Total wall clock budget for the whole run, so the CI job
# never sits on a dead server list.
MAX_TEST_SECONDS = 480

PPP_UNIT = 0
PPP_INTERFACE = f"ppp{PPP_UNIT}"


def run_command(command, timeout=15, check=False):

    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            check=check
        )

    except (subprocess.TimeoutExpired, OSError):
        return None


def get_public_ip():
    try:
        request = urllib.request.Request(
            "https://api.ipify.org",
            headers={"User-Agent": "VPNGate-AutoBot/1.0"}
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            return response.read().decode().strip()

    except Exception:
        return None


def get_tunnel_public_ip():
    """Public IP as seen from inside the SSTP tunnel.

    SO_BINDTODEVICE (curl --interface) forces the request out of
    the PPP interface without touching the default route, so the
    runner keeps its own connectivity.
    """

    result = run_command(
        [
            "sudo", "-n",
            "curl", "-s",
            "--max-time", "10",
            "--interface", PPP_INTERFACE,
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


def load_sstp_servers():
    path = Path(INPUT_FILE)

    if not path.exists():
        raise FileNotFoundError(INPUT_FILE)

    with path.open("r", encoding="utf-8") as file:
        servers = json.load(file)

    if not isinstance(servers, list):
        raise ValueError("SSTP data must be a JSON list.")

    return servers


def stop_process(process):
    if process is None or process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)

    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    except ProcessLookupError:
        pass


def cleanup_ppp_interface():

    run_command(
        ["sudo", "-n", "ip", "link", "delete", PPP_INTERFACE],
        timeout=10
    )

    # pppd may leave the unit busy if sstpc was killed hard.
    run_command(
        ["sudo", "-n", "pkill", "-f", f"pppd.*{PPP_INTERFACE}"],
        timeout=10
    )


def print_log(title, path):
    print()
    print(f"========== {title} ==========")

    if path.exists():
        content = path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        print(content[-8000:] if content else "Log file is empty.")
    else:
        print("Log file was not created.")


def test_sstp_server(server):
    hostname = str(
        server.get("sstp_hostname", "")
    ).strip()

    port = server.get("sstp_port", 443)

    username = str(server.get("username", "vpn"))
    password = str(server.get("password", "vpn"))

    if not hostname or not isinstance(port, int):
        return False

    if not 1 <= port <= 65535:
        return False

    if port != 443:
        hostname = f"{hostname}:{port}"

    original_ip = get_public_ip()

    if not original_ip:
        print("Could not determine original public IP.")
        return False

    process = None

    try:
        with TemporaryDirectory() as temp_dir:
            sstp_log = Path(temp_dir) / "sstp.log"
            ppp_log = Path(temp_dir) / "pppd.log"

            # No defaultroute / replacedefaultroute here: the runner
            # only needs the PPP interface to exist so the public-IP
            # check can be pinned to it with SO_BINDTODEVICE.
            command = [
                "sudo", "-n", "sstpc",
                "--log-level", "4",
                "--log-stderr",
                "--user", username,
                "--password", password,
                hostname,
                "--",
                "debug",
                "logfile", str(ppp_log),
                "unit", str(PPP_UNIT),
                "noipdefault",
                "noccp",
                "novj",
                "noipv6",
                "nodefaultroute",
                "nodetach",
                "noauth",
                "require-mschap-v2",
                "refuse-eap",
                "refuse-pap",
                "refuse-chap",
                "refuse-mschap"
            ]

            with sstp_log.open(
                "w",
                encoding="utf-8"
            ) as log_file:

                process = subprocess.Popen(
                    command,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )

                start_time = time.monotonic()

                while (
                    time.monotonic() - start_time
                    < CONNECTION_TIMEOUT
                ):

                    if process.poll() is not None:
                        break

                    time.sleep(3)

                    tunnel_ip = get_tunnel_public_ip()

                    if tunnel_ip and tunnel_ip != original_ip:

                        print(
                            f"Original IP: {original_ip}"
                        )

                        print(
                            f"VPN public IP: {tunnel_ip}"
                        )

                        print_log(
                            "PPP DIAGNOSTIC LOG",
                            ppp_log
                        )

                        print_log(
                            "SSTP LOG",
                            sstp_log
                        )

                        return True

                print_log(
                    "PPP DIAGNOSTIC LOG",
                    ppp_log
                )

                print_log(
                    "SSTP LOG",
                    sstp_log
                )

                return False

    except Exception as error:
        print(f"SSTP test error: {error}")
        return False

    finally:
        stop_process(process)


def save_selected_servers(servers):
    output_path = Path(OUTPUT_FILE)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            servers,
            file,
            ensure_ascii=False,
            indent=4
        )


def main():
    servers = load_sstp_servers()

    selected = []
    tested_count = 0

    deadline = time.monotonic() + MAX_TEST_SECONDS

    print()
    print("========== REAL SSTP CONNECTION TEST ==========")
    print(
        f"Limits: {MAX_SERVERS_TO_TEST} servers / "
        f"{MAX_TEST_SECONDS}s wall clock / "
        f"{TARGET_SERVERS} target"
    )

    for server in servers:

        if len(selected) >= TARGET_SERVERS:
            break

        if tested_count >= MAX_SERVERS_TO_TEST:
            print(
                f"Reached test limit ({MAX_SERVERS_TO_TEST} servers)."
            )
            break

        if time.monotonic() > deadline:
            print("Reached time limit; stopping test run.")
            break

        tested_count += 1

        hostname = server.get("sstp_hostname", "")
        ip = server.get("ip", "")

        print()
        print(
            f"{tested_count}. Testing {ip} | {hostname}"
        )

        try:
            if test_sstp_server(server):
                selected.append(server)

                print(
                    "RESULT: REAL SSTP CONNECTION CONFIRMED"
                )

            else:
                print(
                    "RESULT: SSTP CONNECTION FAILED"
                )

        finally:
            cleanup_ppp_interface()

        print(
            f"Confirmed connections: "
            f"{len(selected)}/{TARGET_SERVERS}"
        )

    save_selected_servers(selected)

    print()
    print("========== SSTP TEST SUMMARY ==========")

    print(f"Total servers available: {len(servers)}")
    print(f"Servers tested: {tested_count}")
    print(f"Real SSTP connections: {len(selected)}")
    print(f"Target servers: {TARGET_SERVERS}")

    if len(selected) >= TARGET_SERVERS:
        print("Selection status: TARGET REACHED")
    else:
        print("Selection status: NOT ENOUGH VERIFIED SERVERS")

    print("=======================================")


if __name__ == "__main__":
    main()
