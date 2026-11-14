
import json
import socket

from pathlib import Path


INPUT_FILE = "output/sstp_servers.json"

OUTPUT_FILE = "output/selected_sstp_servers.json"

TARGET_SERVERS = 10

CONNECTION_TIMEOUT = 3


def check_tcp_port(host, port, timeout=CONNECTION_TIMEOUT):

    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout
        ):
            return True

    except (OSError, TimeoutError):
        return False


def load_sstp_servers():

    input_path = Path(INPUT_FILE)

    if not input_path.exists():
        raise FileNotFoundError(
            f"SSTP input file not found: {INPUT_FILE}"
        )

    with input_path.open(
        "r",
        encoding="utf-8"
    ) as file:

        servers = json.load(file)

    if not isinstance(servers, list):
        raise ValueError(
            "SSTP data must be a JSON list."
        )

    return servers


def test_sstp_servers(servers):

    selected_servers = []

    tested_count = 0

    print()
    print("========== SSTP SERVER TEST ==========")

    for server in servers:

        if len(selected_servers) >= TARGET_SERVERS:
            break

        hostname = server.get(
            "sstp_hostname", ""
        ).strip()

        port = server.get("sstp_port")

        ip = server.get("ip", "")

        if not hostname or not isinstance(port, int):
            continue

        tested_count += 1

        is_open = check_tcp_port(
            hostname,
            port
        )

        status = "OPEN" if is_open else "CLOSED/BLOCKED"

        print(
            f"{tested_count}. "
            f"{ip} | "
            f"{hostname}:{port} | "
            f"{status}"
        )

        if is_open:

            selected_servers.append(server)

            print("   SELECTED: SSTP TCP port is reachable")

        print(
            f"Healthy SSTP servers: "
            f"{len(selected_servers)}/{TARGET_SERVERS}"
        )

    print()
    print("========== SSTP TEST SUMMARY ==========")

    print(f"Total SSTP servers available: {len(servers)}")
    print(f"Servers tested: {tested_count}")
    print(f"Healthy SSTP servers selected: {len(selected_servers)}")
    print(f"Target servers: {TARGET_SERVERS}")

    if len(selected_servers) >= TARGET_SERVERS:
        print("Selection status: TARGET REACHED")
    else:
        print("Selection status: NOT ENOUGH HEALTHY SERVERS")

    print("=======================================")

    return selected_servers


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

    print()
    print(f"Selected SSTP servers saved: {len(servers)}")
    print(f"Output file: {OUTPUT_FILE}")


def main():

    servers = load_sstp_servers()

    selected = test_sstp_servers(servers)

    save_selected_servers(selected)

    print()
    print("SSTP port testing completed.")


if __name__ == "__main__":
    main()
