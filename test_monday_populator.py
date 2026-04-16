"""
Tests for monday_populator.py

Selenium and requests are fully mocked — no browser or network calls.
Run with: pytest tests/test_monday_populator.py -v
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import monday_populator as mp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PLATFORM_BASE_URL", "https://platform.example.com")
    monkeypatch.setenv("MONDAY_TRANSFERRED_GROUP_ID", "group_transferred")
    monkeypatch.setattr(mp, "DOWNLOAD_DIR", tmp_path / "inbox")


# ---------------------------------------------------------------------------
# is_model()
# ---------------------------------------------------------------------------

class TestIsModel:
    def test_real_model_number_returns_true(self):
        assert mp.is_model("WFW5605MC") is True

    def test_empty_string_returns_false(self):
        assert mp.is_model("") is False

    def test_delete_code_returns_false(self):
        assert mp.is_model("FREIGHT") is False

    def test_service_code_returns_false(self):
        assert mp.is_model("X001") is False

    def test_parts_code_returns_false(self):
        assert mp.is_model("WATERLINE") is False

    def test_labor_code_returns_false(self):
        assert mp.is_model("WASHERIN") is False

    def test_case_sensitive_match(self):
        # NON_MODEL_CODES are uppercase — lowercase should pass through as a model
        assert mp.is_model("freight") is True


# ---------------------------------------------------------------------------
# get_next_business_day()
# ---------------------------------------------------------------------------

class TestGetNextBusinessDay:
    def test_monday_through_thursday_adds_one_day(self):
        for weekday in range(0, 4):  # Mon=0 .. Thu=3
            with patch("monday_populator.datetime") as mock_dt:
                mock_dt.today.return_value = datetime(2024, 1, 1 + weekday)  # Mon Jan 1
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = mp.get_next_business_day()
                assert (result - datetime(2024, 1, 1 + weekday)).days == 1

    def test_friday_adds_three_days(self):
        friday = datetime(2024, 1, 5)  # Known Friday
        with patch("monday_populator.datetime") as mock_dt:
            mock_dt.today.return_value = friday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = mp.get_next_business_day()
            assert (result - friday).days == 3

    def test_saturday_adds_two_days(self):
        saturday = datetime(2024, 1, 6)
        with patch("monday_populator.datetime") as mock_dt:
            mock_dt.today.return_value = saturday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = mp.get_next_business_day()
            assert (result - saturday).days == 2


# ---------------------------------------------------------------------------
# parse_orders()
# ---------------------------------------------------------------------------

@pytest.fixture
def make_xlsx(tmp_path):
    """Helper that writes a minimal batch invoice xlsx and returns its path."""
    from openpyxl import Workbook

    def _make(rows):
        wb = Workbook()
        ws = wb.active
        ws.append(["Order #", "Model Number", "Truck"])
        for row in rows:
            ws.append(row)
        path = str(tmp_path / "batch.xlsx")
        wb.save(path)
        return path

    return _make


class TestParseOrders:
    def test_counts_model_rows(self, make_xlsx):
        path = make_xlsx([
            ["1001", "WFW5605MC", "TRUCK1"],
            ["1001", "MED6030MW", "TRUCK1"],
        ])
        result = mp.parse_orders(path)
        # 2 models + 1 = 3
        assert result["1001"] == 3

    def test_excludes_storage_truck(self, make_xlsx):
        path = make_xlsx([["2001", "WFW5605MC", "STORAGE"]])
        result = mp.parse_orders(path)
        assert "2001" not in result

    def test_excludes_unpaid_truck(self, make_xlsx):
        path = make_xlsx([["2002", "WFW5605MC", "UNPAID"]])
        result = mp.parse_orders(path)
        assert "2002" not in result

    def test_ignores_delete_codes(self, make_xlsx):
        path = make_xlsx([
            ["3001", "WFW5605MC", "TRUCK1"],
            ["3001", "FREIGHT",   "TRUCK1"],
        ])
        result = mp.parse_orders(path)
        # 1 model + 1 = 2
        assert result["3001"] == 2

    def test_minimum_one_model_row(self, make_xlsx):
        # Order with no models (only parts) should still get at least 1+1=2
        path = make_xlsx([["4001", "WATERLINE", "TRUCK1"]])
        result = mp.parse_orders(path)
        assert result["4001"] == 2

    def test_skips_empty_rows(self, make_xlsx):
        path = make_xlsx([
            ["5001", "WFW5605MC", "TRUCK1"],
            [None, None, None],
        ])
        result = mp.parse_orders(path)
        assert "5001" in result

    def test_skips_none_order_number(self, make_xlsx):
        path = make_xlsx([[None, "WFW5605MC", "TRUCK1"]])
        result = mp.parse_orders(path)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# get_or_create_group()
# ---------------------------------------------------------------------------

class TestGetOrCreateGroup:
    def test_returns_existing_group_id(self):
        groups = [{"id": "grp_1", "title": "060124PIX"}]
        result = mp.get_or_create_group("token", "board_1", "060124PIX", groups)
        assert result == "grp_1"

    def test_creates_group_when_not_found(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"create_group": {"id": "grp_new"}}}
        with patch("monday_populator.requests.post", return_value=mock_resp):
            result = mp.get_or_create_group("token", "board_1", "060224PIX", [])
        assert result == "grp_new"


# ---------------------------------------------------------------------------
# create_item()
# ---------------------------------------------------------------------------

class TestCreateItem:
    def test_posts_to_monday_api(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"create_item": {"id": "new_item"}}}
        with patch("monday_populator.requests.post", return_value=mock_resp) as mock_post:
            mp.create_item("token", "board_1", "grp_1", "1001", datetime(2024, 6, 1))
        mock_post.assert_called_once()

    def test_logs_warning_on_api_error(self, capsys):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"errors": [{"message": "rate limit"}]}
        with patch("monday_populator.requests.post", return_value=mock_resp):
            mp.create_item("token", "board_1", "grp_1", "1001", datetime(2024, 6, 1))
        assert "WARNING" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# populate_monday()
# ---------------------------------------------------------------------------

class TestPopulateMonday:
    def _make_item(self, name, group_id, date_str=None):
        col_value = json.dumps({"date": date_str}) if date_str else None
        return {
            "id": f"item_{name}",
            "name": name,
            "group": {"id": group_id},
            "column_values": [{"id": "date4", "value": col_value}],
        }

    def test_skips_transferred_orders(self):
        orders = {"1001": 2}
        groups = [{"id": "grp_pix", "title": "060124PIX"}]
        items  = [self._make_item("1001", "group_transferred", "2099-01-01")]

        with patch("monday_populator.get_board_items", return_value=(groups, items)), \
             patch("monday_populator.get_or_create_group", return_value="grp_pix"), \
             patch("monday_populator.create_item") as mock_create:
            mp.populate_monday("token", "board_1", orders, datetime(2024, 6, 1))

        mock_create.assert_not_called()

    def test_skips_orders_with_future_date(self):
        orders = {"2001": 2}
        groups = [{"id": "grp_pix", "title": "060124PIX"}]
        items  = [self._make_item("2001", "grp_other", "2099-12-31")]

        with patch("monday_populator.get_board_items", return_value=(groups, items)), \
             patch("monday_populator.get_or_create_group", return_value="grp_pix"), \
             patch("monday_populator.create_item") as mock_create:
            mp.populate_monday("token", "board_1", orders, datetime(2024, 6, 1))

        mock_create.assert_not_called()

    def test_creates_items_for_new_orders(self):
        orders = {"3001": 2}
        groups = []
        items  = []

        with patch("monday_populator.get_board_items", return_value=(groups, items)), \
             patch("monday_populator.get_or_create_group", return_value="grp_new"), \
             patch("monday_populator.create_item") as mock_create, \
             patch("time.sleep"):
            mp.populate_monday("token", "board_1", orders, datetime(2024, 6, 1))

        assert mock_create.call_count == 2


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------

class TestRun:
    def test_returns_false_when_scrape_fails(self):
        with patch("monday_populator.scrape_batch_invoice", return_value=None), \
             patch("monday_populator.get_next_business_day", return_value=datetime(2024, 6, 1)):
            result = mp.run("u", "p", "token", "board_1")
        assert result is False

    def test_returns_false_when_no_orders_parsed(self, tmp_path):
        fake_file = str(tmp_path / "batch.xlsx")
        open(fake_file, "w").close()
        with patch("monday_populator.scrape_batch_invoice", return_value=fake_file), \
             patch("monday_populator.parse_orders", return_value={}), \
             patch("monday_populator.get_next_business_day", return_value=datetime(2024, 6, 1)):
            result = mp.run("u", "p", "token", "board_1")
        assert result is False

    def test_returns_true_on_success(self, tmp_path):
        fake_file = str(tmp_path / "batch.xlsx")
        open(fake_file, "w").close()
        with patch("monday_populator.scrape_batch_invoice", return_value=fake_file), \
             patch("monday_populator.parse_orders", return_value={"1001": 2}), \
             patch("monday_populator.populate_monday"), \
             patch("monday_populator.get_next_business_day", return_value=datetime(2024, 6, 1)):
            result = mp.run("u", "p", "token", "board_1")
        assert result is True
