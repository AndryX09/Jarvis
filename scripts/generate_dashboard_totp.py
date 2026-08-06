from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import secrets
from urllib.parse import quote, urlencode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Jarvis dashboard TOTP secret without overwriting files."
    )
    parser.add_argument("--output", required=True, help="Secret file to create")
    parser.add_argument("--issuer", default="Jarvis", help="Authenticator issuer")
    parser.add_argument("--account", default="dashboard", help="Authenticator account label")
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = Path(args.output).expanduser()
    if not output.parent.is_dir():
        raise SystemExit(f"Parent directory does not exist: {output.parent}")

    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(output, flags, 0o600)
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite existing secret file: {output}") from None
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(secret + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        os.chmod(output, 0o600)

    label = quote(f"{args.issuer}:{args.account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": args.issuer,
            "algorithm": "SHA1",
            "digits": "6",
            "period": "30",
        }
    )
    print(f"Secret file created: {output}")
    print("Sensitive pairing URI (shown once):")
    print(f"otpauth://totp/{label}?{query}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
