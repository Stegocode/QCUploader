"""
monday_client.py
================
Monday.com API client for fetching, parsing, and updating board items.
Column IDs and group IDs are configured via environment variables.
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

MONDAY_API_URL = "https://api.monday.com/v2"

# Board group IDs — set in .env
COMPLETED_GROUP_ID   = os.getenv("MONDAY_COMPLETED_GROUP_ID", "")
TRANSFERRED_GROUP_ID = os.getenv("MONDAY_TRANSFERRED_GROUP_ID", "")

# Column IDs — set in .env
SERIAL_PHOTO_COL = os.getenv("MONDAY_SERIAL_PHOTO_COL", "")
ID_PHOTO_COL     = os.getenv("MONDAY_ID_PHOTO_COL", "")
SERIAL_NUM_COL   = os.getenv("MONDAY_SERIAL_NUM_COL", "")
INVENTORY_ID_COL = os.getenv("MONDAY_INVENTORY_ID_COL", "")
MODEL_COL        = os.getenv("MONDAY_MODEL_COL", "")
STATUS_COL       = os.getenv("MONDAY_STATUS_COL", "status")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {"Authorization": token, "Content-Type": "application/json"}


def _log_error(logger, msg: str):
    if logger:
        logger.error(msg)
    else:
        print(f"  ERROR: {msg}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_completed_items(token: str, board_id: str, logger=None) -> list:
    """Return all items in the completed group, ready for photo transfer."""
    query = f"""
    query {{
      boards(ids: {board_id}) {{
        groups(ids: "{COMPLETED_GROUP_ID}") {{
          items_page {{
            items {{
              id
              name
              column_values {{
                id
                value
                type
              }}
            }}
          }}
        }}
      }}
    }}
    """
    try:
        response = requests.post(
            MONDAY_API_URL,
            json={"query": query},
            headers=_headers(token),
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            _log_error(logger, f"get_completed_items API error: {data['errors']}")
            return []
        return data["data"]["boards"][0]["groups"][0]["items_page"]["items"]
    except Exception as e:
        _log_error(logger, f"get_completed_items failed: {e}")
        return []


def parse_item(item: dict) -> dict:
    """Extract order number and photo asset IDs from a Monday item."""
    asset_ids = {}
    for col in item["column_values"]:
        if col["id"] in (SERIAL_PHOTO_COL, ID_PHOTO_COL) and col["value"]:
            files = json.loads(col["value"]).get("files", [])
            if files:
                asset_ids[col["id"]] = files[0]["assetId"]
    return {
        "order_number":    item["name"],
        "item_id":         item["id"],
        "serial_asset_id": asset_ids.get(SERIAL_PHOTO_COL),
        "id_asset_id":     asset_ids.get(ID_PHOTO_COL),
    }


def get_public_url(token: str, asset_id: str, logger=None) -> str | None:
    """Resolve a Monday asset ID to a public download URL."""
    query = f"{{ assets (ids: {asset_id}) {{ id public_url }} }}"
    try:
        response = requests.post(
            MONDAY_API_URL,
            json={"query": query},
            headers=_headers(token),
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            _log_error(logger, f"get_public_url error (asset {asset_id}): {data['errors']}")
            return None
        return data["data"]["assets"][0]["public_url"]
    except Exception as e:
        _log_error(logger, f"get_public_url failed (asset {asset_id}): {e}")
        return None


def download_photo(public_url: str, dest_path: str, logger=None) -> bool:
    """Stream a photo from a public URL to a local file."""
    try:
        response = requests.get(public_url, stream=True, timeout=30)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  Downloaded: {dest_path}")
        return True
    except Exception as e:
        _log_error(logger, f"download_photo failed ({public_url}): {e}")
        return False


def mark_transferred(token: str, board_id: str, item_id: str, logger=None):
    """Move an item's status column to index 0 (Transferred)."""
    mutation = """
    mutation changeStatus($boardId: ID!, $itemId: ID!, $value: JSON!) {
      change_column_value(
        board_id: $boardId,
        item_id: $itemId,
        column_id: "status",
        value: $value
      ) { id }
    }
    """
    variables = {
        "boardId": str(board_id),
        "itemId":  str(item_id),
        "value":   json.dumps({"index": 0}),
    }
    try:
        response = requests.post(
            MONDAY_API_URL,
            json={"query": mutation, "variables": variables},
            headers=_headers(token),
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        if "errors" in result:
            _log_error(logger, f"mark_transferred error (item {item_id}): {result['errors']}")
        else:
            print(f"  Status updated to TRANSFERRED for item {item_id}")
        return result
    except Exception as e:
        _log_error(logger, f"mark_transferred failed (item {item_id}): {e}")
        return None
