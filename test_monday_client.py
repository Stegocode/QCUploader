"""
Tests for monday_client.py

All HTTP calls are mocked — no live Monday.com API calls are made.
Run with: pytest tests/test_monday_client.py -v
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import monday_client as mc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_env(monkeypatch):
    monkeypatch.setenv("MONDAY_COMPLETED_GROUP_ID",   "group_completed")
    monkeypatch.setenv("MONDAY_TRANSFERRED_GROUP_ID", "group_transferred")
    monkeypatch.setenv("MONDAY_SERIAL_PHOTO_COL",     "col_serial")
    monkeypatch.setenv("MONDAY_ID_PHOTO_COL",         "col_id")


@pytest.fixture
def mock_response():
    def _make(payload, status=200, raise_for_status=False):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = payload
        if raise_for_status:
            r.raise_for_status.side_effect = Exception("HTTP Error")
        else:
            r.raise_for_status.return_value = None
        return r
    return _make


@pytest.fixture
def sample_item():
    return {
        "id": "item_1",
        "name": "12345",
        "column_values": [
            {"id": "col_serial", "value": json.dumps({"files": [{"assetId": "asset_s"}]})},
            {"id": "col_id",     "value": json.dumps({"files": [{"assetId": "asset_i"}]})},
        ],
    }


# ---------------------------------------------------------------------------
# _headers()
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_returns_correct_keys(self):
        headers = mc._headers("mytoken")
        assert headers["Authorization"] == "mytoken"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# _log_error()
# ---------------------------------------------------------------------------

class TestLogError:
    def test_calls_logger_error_when_provided(self):
        logger = MagicMock()
        mc._log_error(logger, "something went wrong")
        logger.error.assert_called_once_with("something went wrong")

    def test_prints_when_no_logger(self, capsys):
        mc._log_error(None, "fallback error")
        assert "fallback error" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# get_completed_items()
# ---------------------------------------------------------------------------

class TestGetCompletedItems:
    def test_returns_items_on_success(self, mock_response):
        payload = {
            "data": {
                "boards": [{
                    "groups": [{
                        "items_page": {
                            "items": [{"id": "1", "name": "order_1", "column_values": []}]
                        }
                    }]
                }]
            }
        }
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            result = mc.get_completed_items("token", "board_1")
        assert len(result) == 1
        assert result[0]["name"] == "order_1"

    def test_returns_empty_list_on_api_error(self, mock_response):
        payload = {"errors": [{"message": "Unauthorized"}]}
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            result = mc.get_completed_items("token", "board_1")
        assert result == []

    def test_returns_empty_list_on_exception(self):
        with patch("monday_client.requests.post", side_effect=Exception("Network error")):
            result = mc.get_completed_items("token", "board_1")
        assert result == []

    def test_logs_error_on_api_error(self, mock_response):
        payload = {"errors": [{"message": "Bad token"}]}
        logger = MagicMock()
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            mc.get_completed_items("token", "board_1", logger=logger)
        logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# parse_item()
# ---------------------------------------------------------------------------

class TestParseItem:
    def test_parses_order_number_and_asset_ids(self, sample_item):
        result = mc.parse_item(sample_item)
        assert result["order_number"]    == "12345"
        assert result["item_id"]         == "item_1"
        assert result["serial_asset_id"] == "asset_s"
        assert result["id_asset_id"]     == "asset_i"

    def test_returns_none_for_missing_assets(self):
        item = {
            "id": "item_2",
            "name": "99999",
            "column_values": [
                {"id": "col_serial", "value": None},
                {"id": "col_id",     "value": None},
            ],
        }
        result = mc.parse_item(item)
        assert result["serial_asset_id"] is None
        assert result["id_asset_id"]     is None

    def test_returns_none_for_empty_files_list(self):
        item = {
            "id": "item_3",
            "name": "77777",
            "column_values": [
                {"id": "col_serial", "value": json.dumps({"files": []})},
            ],
        }
        result = mc.parse_item(item)
        assert result["serial_asset_id"] is None

    def test_ignores_unrecognised_columns(self, sample_item):
        sample_item["column_values"].append({"id": "col_unknown", "value": "irrelevant"})
        result = mc.parse_item(sample_item)
        assert result["serial_asset_id"] == "asset_s"


# ---------------------------------------------------------------------------
# get_public_url()
# ---------------------------------------------------------------------------

class TestGetPublicUrl:
    def test_returns_url_on_success(self, mock_response):
        payload = {"data": {"assets": [{"id": "a1", "public_url": "https://cdn.example.com/photo.jpg"}]}}
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            url = mc.get_public_url("token", "a1")
        assert url == "https://cdn.example.com/photo.jpg"

    def test_returns_none_on_api_error(self, mock_response):
        payload = {"errors": [{"message": "Not found"}]}
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            url = mc.get_public_url("token", "a1")
        assert url is None

    def test_returns_none_on_exception(self):
        with patch("monday_client.requests.post", side_effect=Exception("timeout")):
            url = mc.get_public_url("token", "a1")
        assert url is None


# ---------------------------------------------------------------------------
# download_photo()
# ---------------------------------------------------------------------------

class TestDownloadPhoto:
    def test_writes_file_and_returns_true(self, tmp_path):
        dest = str(tmp_path / "photo.jpg")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"fake_image_data"]
        with patch("monday_client.requests.get", return_value=mock_resp):
            result = mc.download_photo("https://cdn.example.com/photo.jpg", dest)
        assert result is True
        assert open(dest, "rb").read() == b"fake_image_data"

    def test_returns_false_on_http_error(self, tmp_path):
        dest = str(tmp_path / "photo.jpg")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404")
        with patch("monday_client.requests.get", return_value=mock_resp):
            result = mc.download_photo("https://cdn.example.com/photo.jpg", dest)
        assert result is False

    def test_returns_false_on_exception(self, tmp_path):
        dest = str(tmp_path / "photo.jpg")
        with patch("monday_client.requests.get", side_effect=Exception("network")):
            result = mc.download_photo("https://cdn.example.com/photo.jpg", dest)
        assert result is False

    def test_logs_error_on_failure(self, tmp_path):
        dest = str(tmp_path / "photo.jpg")
        logger = MagicMock()
        with patch("monday_client.requests.get", side_effect=Exception("network")):
            mc.download_photo("https://cdn.example.com/photo.jpg", dest, logger=logger)
        logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# mark_transferred()
# ---------------------------------------------------------------------------

class TestMarkTransferred:
    def test_returns_result_on_success(self, mock_response):
        payload = {"data": {"change_column_value": {"id": "item_1"}}}
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            result = mc.mark_transferred("token", "board_1", "item_1")
        assert result["data"]["change_column_value"]["id"] == "item_1"

    def test_logs_error_on_api_error(self, mock_response):
        payload = {"errors": [{"message": "Permission denied"}]}
        logger = MagicMock()
        with patch("monday_client.requests.post", return_value=mock_response(payload)):
            mc.mark_transferred("token", "board_1", "item_1", logger=logger)
        logger.error.assert_called_once()

    def test_returns_none_on_exception(self):
        with patch("monday_client.requests.post", side_effect=Exception("timeout")):
            result = mc.mark_transferred("token", "board_1", "item_1")
        assert result is None
