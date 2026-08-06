from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Jarvis MCP Bearer token without overwriting files."
    )
    parser.add_argument("--output", required=True, help="Bearer token file to create")
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = Path(args.output).expanduser()
    if not output.parent.is_dir():
        raise SystemExit(f"Parent directory does not exist: {output.parent}")

    token = secrets.token_urlsafe(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(output, flags, 0o600)
    except FileExistsError:
        raise SystemExit(f"Refusing to overwrite existing token file: {output}") from None
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        os.chmod(output, 0o600)

    print(f"Bearer token file created: {output}")
    print("Bearer token (shown once):")
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
