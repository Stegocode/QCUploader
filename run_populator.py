"""
run_populator.py
================
Entry point for the Monday Populator.
Reads credentials from .env and kicks off the daily sync.

Usage:
    python run_populator.py
"""

import os
from dotenv import load_dotenv
import monday_populator as mp

load_dotenv()

HS_USERNAME  = os.getenv("HS_USERNAME")
HS_PASSWORD  = os.getenv("HS_PASSWORD")
MONDAY_TOKEN = os.getenv("MONDAY_API_TOKEN")
BOARD_ID     = os.getenv("MONDAY_BOARD_ID")

if not all([HS_USERNAME, HS_PASSWORD, MONDAY_TOKEN, BOARD_ID]):
    raise EnvironmentError(
        "Missing required environment variables. "
        "Copy .env.example to .env and fill in all values."
    )

if __name__ == "__main__":
    mp.run(HS_USERNAME, HS_PASSWORD, MONDAY_TOKEN, BOARD_ID)
