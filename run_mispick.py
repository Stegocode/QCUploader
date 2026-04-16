"""
run_mispick.py
==============
Entry point for the Mispick Checker.
Reads credentials and config from .env.

Usage:
    python run_mispick.py --serial path/to/serial-number-inventory.csv
"""

import argparse
import os
from dotenv import load_dotenv
import mispick_checker as mc

load_dotenv()

MONDAY_TOKEN = os.getenv("MONDAY_API_TOKEN")
BOARD_ID     = os.getenv("MONDAY_BOARD_ID")

if not all([MONDAY_TOKEN, BOARD_ID]):
    raise EnvironmentError(
        "Missing MONDAY_API_TOKEN or MONDAY_BOARD_ID. "
        "Copy .env.example to .env and fill in all values."
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run mispick and misreceive checks")
    parser.add_argument(
        "--serial",
        required=True,
        help="Path to the HomeSource serial inventory CSV export",
    )
    args = parser.parse_args()

    if not os.path.exists(args.serial):
        raise FileNotFoundError(f"Serial inventory file not found: {args.serial}")

    results = mc.run(MONDAY_TOKEN, BOARD_ID, args.serial)

    flagged = [r for r in results if r["status"] not in ("OK", "NO_DATA", "NO_MATCH")]
    if flagged:
        print(f"\n  {len(flagged)} item(s) flagged and updated in Monday.")
    else:
        print("\n  No issues found — clean run.")
