"""
mispick_checker.py
==================
Detects two categories of warehouse errors by comparing Monday.com
AI-extracted photo data against the serial inventory export:

  MISPICK     — The model on the picked item does not match what the
                sales order called for (wrong item sent to customer).
                Detected when: serial_export_model != col5_model_extract

  MISRECEIVE  — The model on the box does not match the inventory label
                on the item itself (wrong item received into inventory).
                Detected when: col5_model_extract != col8_label_model_extract

Flow:
  1. Load serial inventory CSV export from HomeSource
  2. Fetch all items in the Monday completed group
  3. For each item, read AI-extracted column values
  4. Cross-reference inventory ID to confirm unit match
  5. Run mispick and misreceive checks
  6. Update Monday status on any flagged rows
  7. Return a summary report
"""

import csv
import os

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONDAY_API_URL       = "https://api.monday.com/v2"
COMPLETED_GROUP_ID   = os.getenv("MONDAY_COMPLETED_GROUP_ID", "")
TRANSFERRED_GROUP_ID = os.getenv("MONDAY_TRANSFERRED_GROUP_ID", "")

# Column IDs — reuse existing env vars where possible
COL_STATUS             = os.getenv("MONDAY_STATUS_COL", "status")
COL_MODEL_UPLOAD       = os.getenv("MONDAY_SERIAL_PHOTO_COL", "")   # col 3 — box photo upload
COL_ID_UPLOAD          = os.getenv("MONDAY_ID_PHOTO_COL", "")       # col 4 — label photo upload
COL_MODEL_EXTRACT      = os.getenv("MONDAY_MODEL_COL", "")          # col 5 — model # from box photo
COL_SERIAL_EXTRACT     = os.getenv("MONDAY_SERIAL_NUM_COL", "")     # col 6 — serial # from box photo
COL_INV_ID_EXTRACT     = os.getenv("MONDAY_INVENTORY_ID_COL", "")   # col 7 — inventory ID from label
COL_LABEL_MODEL_EXTRACT = os.getenv("MONDAY_LABEL_MODEL_COL", "")   # col 8 — model # from label photo

# Status index values — must match your Monday board status column config
STATUS_MISPICK    = os.getenv("MONDAY_STATUS_MISPICK_INDEX",    "1")
STATUS_MISRECEIVE = os.getenv("MONDAY_STATUS_MISRECEIVE_INDEX", "2")


# ---------------------------------------------------------------------------
# Serial inventory loader
# ---------------------------------------------------------------------------

def load_serial_inventory(csv_path: str) -> dict:
    """
    Load the HomeSource serial inventory CSV export.

    Returns a dict keyed by inventory_id:
        {
            inventory_id: {
                "order_number": str,
                "model":        str (uppercase),
            }
        }
    Only includes rows that are allocated to an order (order_number is present).
    """
    inventory = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            order_num = str(row.get("Order #", "") or "").strip().replace(".0", "")
            inv_id    = str(row.get("Inventory Id", "") or "").strip().replace(".0", "")
            model     = str(row.get("Model", "") or "").strip().upper()

            if not order_num or not inv_id or not model:
                continue
            # Skip unallocated rows
            if not order_num.isdigit():
                continue

            inventory[inv_id] = {
                "order_number": order_num,
                "model":        model,
            }
    return inventory


# ---------------------------------------------------------------------------
# Monday API helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> dict:
    return {"Authorization": token, "Content-Type": "application/json"}


def get_completed_items(token: str, board_id: str) -> list:
    """Fetch all items in the completed group with their AI-extracted column values."""
    col_ids = ", ".join(f'"{c}"' for c in [
        COL_MODEL_EXTRACT,
        COL_SERIAL_EXTRACT,
        COL_INV_ID_EXTRACT,
        COL_LABEL_MODEL_EXTRACT,
        COL_STATUS,
    ] if c)

    query = f"""
    query {{
      boards(ids: {board_id}) {{
        groups(ids: "{COMPLETED_GROUP_ID}") {{
          items_page {{
            items {{
              id
              name
              column_values(ids: [{col_ids}]) {{
                id
                text
                value
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
            print(f"  ERROR fetching completed items: {data['errors']}")
            return []
        return data["data"]["boards"][0]["groups"][0]["items_page"]["items"]
    except Exception as e:
        print(f"  ERROR fetching completed items: {e}")
        return []


def update_status(token: str, board_id: str, item_id: str, status_index: str, label: str):
    """Update the status column on a Monday item."""
    import json
    mutation = """
    mutation ($boardId: ID!, $itemId: ID!, $colId: String!, $value: JSON!) {
      change_column_value(
        board_id: $boardId,
        item_id:  $itemId,
        column_id: $colId,
        value:    $value
      ) { id }
    }
    """
    variables = {
        "boardId": str(board_id),
        "itemId":  str(item_id),
        "colId":   COL_STATUS,
        "value":   json.dumps({"index": int(status_index)}),
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
            print(f"  ERROR updating status for item {item_id}: {result['errors']}")
            return False
        print(f"  {label} flagged — item {item_id}")
        return True
    except Exception as e:
        print(f"  ERROR updating status for item {item_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Item parser
# ---------------------------------------------------------------------------

def parse_item(item: dict) -> dict:
    """Extract relevant column values from a Monday item into a flat dict."""
    col_map = {c["id"]: c.get("text", "") or "" for c in item["column_values"]}
    return {
        "item_id":             item["id"],
        "order_number":        item["name"].strip(),
        "model_extract":       col_map.get(COL_MODEL_EXTRACT,       "").strip().upper(),
        "serial_extract":      col_map.get(COL_SERIAL_EXTRACT,      "").strip().upper(),
        "inv_id_extract":      col_map.get(COL_INV_ID_EXTRACT,      "").strip().replace(".0", ""),
        "label_model_extract": col_map.get(COL_LABEL_MODEL_EXTRACT, "").strip().upper(),
    }


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def check_item(parsed: dict, inventory: dict) -> dict:
    """
    Run mispick and misreceive checks on a single item.

    Returns a result dict:
        {
            "item_id":      str,
            "order_number": str,
            "inv_id":       str,
            "status":       "OK" | "MISPICK" | "MISRECEIVE" | "BOTH" | "NO_DATA" | "NO_MATCH",
            "expected_model":      str,
            "model_extract":       str,
            "label_model_extract": str,
            "notes":               str,
        }
    """
    item_id      = parsed["item_id"]
    order_number = parsed["order_number"]
    inv_id       = parsed["inv_id_extract"]
    model_box    = parsed["model_extract"]
    model_label  = parsed["label_model_extract"]

    # Can't check without AI-extracted data
    if not model_box and not model_label:
        return {
            "item_id":             item_id,
            "order_number":        order_number,
            "inv_id":              inv_id,
            "status":              "NO_DATA",
            "expected_model":      "",
            "model_extract":       model_box,
            "label_model_extract": model_label,
            "notes":               "AI extraction columns are empty — photos may not be processed yet",
        }

    # Look up expected model from serial inventory via inventory ID
    inv_record     = inventory.get(inv_id)
    expected_model = inv_record["model"] if inv_record else ""

    if not inv_record:
        # Fall back to order number match if inventory ID not found
        order_matches = [v for v in inventory.values() if v["order_number"] == order_number]
        if order_matches:
            expected_model = order_matches[0]["model"]
            notes = f"Matched by order number (inv_id '{inv_id}' not found in export)"
        else:
            return {
                "item_id":             item_id,
                "order_number":        order_number,
                "inv_id":              inv_id,
                "status":              "NO_MATCH",
                "expected_model":      "",
                "model_extract":       model_box,
                "label_model_extract": model_label,
                "notes":               f"Order {order_number} / inv_id '{inv_id}' not found in serial export",
            }
    else:
        notes = ""

    # Run checks
    is_misreceive = bool(model_box and model_label and model_box != model_label)
    is_mispick    = bool(expected_model and model_box and expected_model != model_box)

    if is_misreceive and is_mispick:
        status = "BOTH"
        notes  = f"Expected {expected_model} | Box shows {model_box} | Label shows {model_label}"
    elif is_misreceive:
        status = "MISRECEIVE"
        notes  = f"Box model {model_box} ≠ label model {model_label}"
    elif is_mispick:
        status = "MISPICK"
        notes  = f"Expected {expected_model} but picked {model_box}"
    else:
        status = "OK"
        notes  = notes or f"All checks passed — model {model_box}"

    return {
        "item_id":             item_id,
        "order_number":        order_number,
        "inv_id":              inv_id,
        "status":              status,
        "expected_model":      expected_model,
        "model_extract":       model_box,
        "label_model_extract": model_label,
        "notes":               notes,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(token: str, board_id: str, serial_csv_path: str) -> list:
    """
    Run the full mispick/misreceive check against the completed group.

    Args:
        token:           Monday API token
        board_id:        Monday board ID (Daily Serials board)
        serial_csv_path: Path to the HomeSource serial inventory CSV export

    Returns:
        List of result dicts, one per item checked.
    """
    print("\n=== MISPICK CHECKER ===")

    print("  Loading serial inventory...")
    inventory = load_serial_inventory(serial_csv_path)
    print(f"  Loaded {len(inventory)} allocated units from export")

    print("  Fetching completed items from Monday...")
    items = get_completed_items(token, board_id)
    print(f"  Found {len(items)} items to check")

    results   = []
    counts    = {"OK": 0, "MISPICK": 0, "MISRECEIVE": 0, "BOTH": 0, "NO_DATA": 0, "NO_MATCH": 0}

    for item in items:
        parsed = parse_item(item)
        result = check_item(parsed, inventory)
        results.append(result)

        status = result["status"]
        counts[status] = counts.get(status, 0) + 1

        if status == "OK":
            continue

        print(f"  [{status}] Order {result['order_number']} | {result['notes']}")

        # Update Monday status
        if status in ("MISPICK", "BOTH"):
            update_status(token, board_id, result["item_id"], STATUS_MISPICK, "MISPICK")
        if status in ("MISRECEIVE", "BOTH"):
            update_status(token, board_id, result["item_id"], STATUS_MISRECEIVE, "MISRECEIVE")

    # Summary
    print("\n" + "-" * 50)
    print(f"  RESULTS: {len(items)} items checked")
    print(f"  OK          : {counts['OK']}")
    print(f"  MISPICK     : {counts['MISPICK']}")
    print(f"  MISRECEIVE  : {counts['MISRECEIVE']}")
    print(f"  BOTH        : {counts['BOTH']}")
    print(f"  NO DATA     : {counts['NO_DATA']}")
    print(f"  NO MATCH    : {counts['NO_MATCH']}")
    print("-" * 50)

    return results
