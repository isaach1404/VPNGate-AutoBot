
import base64
import re
from pathlib import Path


def safe_filename(value):
    """
    Remove characters that are not suitable for filenames.
    """
    value = str(value).strip()

    value = re.sub(
        r'[\\/:*?"<>|]',
        "_",
        value
    )

    value = re.sub(r"\s+", "_", value)

    return value[:80] or "Unknown"


def generate_openvpn_configs(
    servers,
    output_dir="output/openvpn"
):
    """
    Convert VPN Gate Base64 configurations
    into individual .ovpn files.
    """

    output_path = Path(output_dir)

    # Create output directory if it does not exist
    output_path.mkdir(
        parents=True,
        exist_ok=True
    )

    generated_files = []
    skipped_servers = 0

    for server in servers:

        encoded_config = server.get(
            "OpenVPN_ConfigData_Base64",
            ""
        ).strip()

        if not encoded_config:
            skipped_servers += 1
            continue

        try:
            # Remove possible whitespace from Base64 data
            encoded_config = "".join(
                encoded_config.split()
            )

            # Decode Base64
            config_bytes = base64.b64decode(
                encoded_config,
                validate=True
            )

            # Convert bytes to readable text
            config_text = config_bytes.decode(
                "utf-8-sig"
            )

            if not config_text.strip():
                skipped_servers += 1
                continue

            # Basic configuration validation
            if "client" not in config_text.lower():
                skipped_servers += 1
                continue

            if "remote " not in config_text.lower():
                skipped_servers += 1
                continue

            country = safe_filename(
                server.get("CountryShort", "Unknown")
            )

            ip = safe_filename(
                server.get("IP", "Unknown")
            )

            filename = f"{country}_{ip}.ovpn"

            file_path = output_path / filename

            # Save OpenVPN configuration
            file_path.write_text(
                config_text,
                encoding="utf-8"
            )

            generated_files.append(str(file_path))

        except (
            ValueError,
            UnicodeDecodeError,
            base64.binascii.Error
        ) as error:

            print(
                f"Could not process server "
                f"{server.get('IP', 'Unknown')}: {error}"
            )

            skipped_servers += 1

    print()
    print("========== OPENVPN GENERATION ==========")
    print(f"Generated files: {len(generated_files)}")
    print(f"Skipped servers: {skipped_servers}")
    print(f"Output directory: {output_path}")
    print("========================================")

    return generated_files
