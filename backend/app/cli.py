from __future__ import annotations

import argparse
import getpass

from .security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("hash-password", help="generate an AI_TOOL_PASSWORD_HASH value")
    args = parser.parse_args()

    if args.command == "hash-password":
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise SystemExit("passwords do not match")
        print(hash_password(first))


if __name__ == "__main__":
    main()
