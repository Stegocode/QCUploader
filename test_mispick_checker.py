"""
Tests for mispick_checker.py

All Monday API calls are mocked — no live connections needed.
Run with: pytest tests/test_mispick_checker.py -v
"""

import csv
import json
import pytest
from unittest.mock import MagicMock, patch

import mispick_checker as mc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("MONDAY_COMPLETED_GROUP_ID",    "group_completed")
    monkeypatch.setenv("MONDAY_STATUS_COL",            "status")
    monkeypatch.setenv("MONDAY_MODEL_COL",             "col_model_extract")
    monkeypatch.setenv("MONDAY_SERIAL_NUM_COL",        "col_serial_extract")
    monkeypatch.setenv("MONDAY_INVENTORY_ID_COL",      "col_inv_id_extract")
    monkeypatch.setenv("MONDAY_LABEL_MODEL_COL",       "col_label_model_extract")
    monkeypatch.setenv("MONDAY_STATUS_MISPICK_INDEX",    "1")
    monkeypatch.setenv("MONDAY_STATUS_MISRECEIVE_INDEX", "2")
    # patch module-level vars that were already loaded
    monkeypatch.setattr(mc, "COL_MODEL_EXTRACT",       "col_model_extract")
    monkeypatch.setattr(mc, "COL_SERIAL_EXTRACT",      "col_serial_extract")
    monkeypatch.setattr(mc, "COL_INV_ID_EXTRACT",      "col_inv_id_extract")
    monkeypatch.setattr(mc, "COL_LABEL_MODEL_EXTRACT", "col_label_model_extract")
    monkeypatch.setattr(mc, "COL_STATUS",              "status")
    monkeypatch.setattr(mc, "STATUS_MISPICK",          "1")
    monkeypatch.setattr(mc, "STATUS_MISRECEIVE",       "2")
    monkeypatch.setattr(mc, "COMPLETED_GROUP_ID",      "group_completed")


@pytest.fixture
def serial_csv(tmp_path):
    """Write a minimal serial inventory CSV and return its path."""
    path = tmp_path / "serial-number-inventory.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Order #", "Inventory Id", "Model"])
        writer.writeheader()
        writer.writerow({"Order #": "1001",  "Inventory Id": "INV001", "Model": "WFW5605MC"})
        writer.writerow({"Order #": "1002",  "Inventory Id": "INV002", "Model": "MED6030MW"})
        writer.writerow({"Order #": "",      "Inventory Id": "INV003", "Model": "GDT695SSJSS"})  # unallocated
    return str(path)


@pytest.fixture
def inventory():
    return {
        "INV001": {"order_number": "1001", "model": "WFW5605MC"},
        "INV002": {"order_number": "1002", "model": "MED6030MW"},
    }


def _make_item(item_id, name, model_extract, serial_extract, inv_id_extract, label_model_extract):
    return {
        "id":   item_id,
        "name": name,
        "column_values": [
            {"id": "col_model_extract",       "text": model_extract,       "value": f'"{model_extract}"'},
            {"id": "col_serial_extract",      "text": serial_extract,      "value": f'"{serial_extract}"'},
            {"id": "col_inv_id_extract",      "text": inv_id_extract,      "value": f'"{inv_id_extract}"'},
            {"id": "col_label_model_extract", "text": label_model_extract, "value": f'"{label_model_extract}"'},
            {"id": "status",                  "text": "",                  "value": "{}"},
        ],
    }


# ---------------------------------------------------------------------------
# load_serial_inventory()
# ---------------------------------------------------------------------------

class TestLoadSerialInventory:
    def test_loads_allocated_rows(self, serial_csv):
        result = mc.load_serial_inventory(serial_csv)
        assert "INV001" in result
        assert "INV002" in result

    def test_skips_unallocated_rows(self, serial_csv):
        result = mc.load_serial_inventory(serial_csv)
        assert "INV003" not in result

    def test_model_is_uppercased(self, serial_csv):
        result = mc.load_serial_inventory(serial_csv)
        assert result["INV001"]["model"] == "WFW5605MC"

    def test_order_number_stripped(self, serial_csv):
        result = mc.load_serial_inventory(serial_csv)
        assert result["INV001"]["order_number"] == "1001"

    def test_empty_csv(self, tmp_path):
        path = tmp_path / "empty.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Order #", "Inventory Id", "Model"])
            writer.writeheader()
        result = mc.load_serial_inventory(str(path))
        assert result == {}


# ---------------------------------------------------------------------------
# parse_item()
# ---------------------------------------------------------------------------

class TestParseItem:
    def test_parses_all_columns(self):
        item = _make_item("i1", "1001", "WFW5605MC", "SN123", "INV001", "WFW5605MC")
        result = mc.parse_item(item)
        assert result["item_id"]             == "i1"
        assert result["order_number"]        == "1001"
        assert result["model_extract"]       == "WFW5605MC"
        assert result["serial_extract"]      == "SN123"
        assert result["inv_id_extract"]      == "INV001"
        assert result["label_model_extract"] == "WFW5605MC"

    def test_handles_missing_columns(self):
        item = {"id": "i2", "name": "1002", "column_values": []}
        result = mc.parse_item(item)
        assert result["model_extract"]       == ""
        assert result["label_model_extract"] == ""


# ---------------------------------------------------------------------------
# check_item()
# ---------------------------------------------------------------------------

class TestCheckItem:
    def _parsed(self, order="1001", inv_id="INV001",
                model_extract="WFW5605MC", label_model="WFW5605MC"):
        return {
            "item_id":             "i1",
            "order_number":        order,
            "inv_id_extract":      inv_id,
            "model_extract":       model_extract,
            "serial_extract":      "SN001",
            "label_model_extract": label_model,
        }

    def test_ok_when_all_match(self, inventory):
        result = mc.check_item(self._parsed(), inventory)
        assert result["status"] == "OK"

    def test_mispick_when_box_model_differs_from_export(self, inventory):
        result = mc.check_item(self._parsed(model_extract="WRONG_MODEL"), inventory)
        assert result["status"] == "MISPICK"

    def test_misreceive_when_box_model_differs_from_label(self, inventory):
        result = mc.check_item(self._parsed(label_model="DIFFERENT_MODEL"), inventory)
        assert result["status"] == "MISRECEIVE"

    def test_both_when_mispick_and_misreceive(self, inventory):
        result = mc.check_item(
            self._parsed(model_extract="WRONG_MODEL", label_model="ALSO_WRONG"),
            inventory,
        )
        assert result["status"] == "BOTH"

    def test_no_data_when_extracts_empty(self, inventory):
        result = mc.check_item(
            self._parsed(model_extract="", label_model=""),
            inventory,
        )
        assert result["status"] == "NO_DATA"

    def test_no_match_when_inv_id_not_in_export(self, inventory):
        result = mc.check_item(
            self._parsed(order="9999", inv_id="INV_UNKNOWN"),
            inventory,
        )
        assert result["status"] == "NO_MATCH"

    def test_falls_back_to_order_number_match(self, inventory):
        # inv_id not found but order number matches
        result = mc.check_item(
            self._parsed(order="1001", inv_id="INV_MISSING"),
            inventory,
        )
        # Should find model via order number fallback
        assert result["status"] in ("OK", "MISPICK", "MISRECEIVE", "BOTH")
        assert result["expected_model"] != ""


# ---------------------------------------------------------------------------
# update_status()
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    def test_returns_true_on_success(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"data": {"change_column_value": {"id": "i1"}}}
        with patch("mispick_checker.requests.post", return_value=mock_resp):
            result = mc.update_status("token", "board_1", "i1", "1", "MISPICK")
        assert result is True

    def test_returns_false_on_api_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"errors": [{"message": "not found"}]}
        with patch("mispick_checker.requests.post", return_value=mock_resp):
            result = mc.update_status("token", "board_1", "i1", "1", "MISPICK")
        assert result is False

    def test_returns_false_on_exception(self):
        with patch("mispick_checker.requests.post", side_effect=Exception("timeout")):
            result = mc.update_status("token", "board_1", "i1", "1", "MISPICK")
        assert result is False


# ---------------------------------------------------------------------------
# run() — integration level
# ---------------------------------------------------------------------------

class TestRun:
    def test_flags_mispick_and_calls_update(self, serial_csv):
        items = [_make_item("i1", "1001", "WRONG_MODEL", "SN001", "INV001", "WRONG_MODEL")]

        with patch("mispick_checker.get_completed_items", return_value=items), \
             patch("mispick_checker.update_status", return_value=True) as mock_update:
            results = mc.run("token", "board_1", serial_csv)

        flagged = [r for r in results if r["status"] == "MISPICK"]
        assert len(flagged) == 1
        mock_update.assert_called()

    def test_flags_misreceive(self, serial_csv):
        items = [_make_item("i1", "1001", "WFW5605MC", "SN001", "INV001", "DIFFERENT_MODEL")]

        with patch("mispick_checker.get_completed_items", return_value=items), \
             patch("mispick_checker.update_status", return_value=True):
            results = mc.run("token", "board_1", serial_csv)

        flagged = [r for r in results if r["status"] == "MISRECEIVE"]
        assert len(flagged) == 1

    def test_clean_run_no_updates(self, serial_csv):
        items = [_make_item("i1", "1001", "WFW5605MC", "SN001", "INV001", "WFW5605MC")]

        with patch("mispick_checker.get_completed_items", return_value=items), \
             patch("mispick_checker.update_status") as mock_update:
            results = mc.run("token", "board_1", serial_csv)

        assert results[0]["status"] == "OK"
        mock_update.assert_not_called()

    def test_empty_monday_board(self, serial_csv):
        with patch("mispick_checker.get_completed_items", return_value=[]):
            results = mc.run("token", "board_1", serial_csv)
        assert results == []
