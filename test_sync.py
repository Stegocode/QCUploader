"""
Tests for sync.py — QCUploader Full Suite Orchestrator

All external calls are mocked — no live connections needed.
Run with: pytest tests/test_sync.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook
import time

import sync
from sync import (
    RunLogger,
    dated_folder,
    send_failure_email,
    download_photos_for_item,
    find_batch_invoice,
    load_order_model_map,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dt():
    return datetime(2024, 6, 15, 10, 30, 0)


@pytest.fixture
def logger(tmp_path, run_dt):
    with patch.object(sync, "LOG_BASE", tmp_path / "logs"):
        yield RunLogger(run_dt)


@pytest.fixture
def parsed_item():
    return {
        "order_number":    "12345",
        "item_id":         "abc",
        "serial_asset_id": "s1",
        "id_asset_id":     "i1",
    }


@pytest.fixture
def order_model_map():
    return {"12345": "WFW5605MC", "12346": "MED6030MW"}


@pytest.fixture
def clean_qc_result():
    return {
        "status":              "OK",
        "item_id":             "abc",
        "order_number":        "12345",
        "inv_id":              "INV001",
        "expected_model":      "WFW5605MC",
        "model_extract":       "WFW5605MC",
        "label_model_extract": "WFW5605MC",
        "notes":               "All checks passed",
    }


def make_batch_xlsx(tmp_path, rows):
    path = tmp_path / "bulk-invoice-test.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Order #", "Model Number", "Truck"])
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# find_batch_invoice()
# ---------------------------------------------------------------------------

class TestFindBatchInvoice:
    def test_finds_bulk_invoice_file(self, tmp_path):
        f = tmp_path / "bulk-invoice-20240615.xlsx"
        f.touch()
        with patch.object(sync, "DOWNLOAD_DIR", tmp_path):
            result = find_batch_invoice()
        assert result == str(f)

    def test_returns_none_when_no_file(self, tmp_path):
        with patch.object(sync, "DOWNLOAD_DIR", tmp_path):
            result = find_batch_invoice()
        assert result is None

    def test_ignores_non_bulk_invoice_files(self, tmp_path):
        (tmp_path / "model-inventory.xlsx").touch()
        with patch.object(sync, "DOWNLOAD_DIR", tmp_path):
            result = find_batch_invoice()
        assert result is None

    def test_returns_most_recent_when_multiple(self, tmp_path):
        f1 = tmp_path / "bulk-invoice-old.xlsx"
        f1.touch()
        time.sleep(0.05)
        f2 = tmp_path / "bulk-invoice-new.xlsx"
        f2.touch()
        with patch.object(sync, "DOWNLOAD_DIR", tmp_path):
            result = find_batch_invoice()
        assert result == str(f2)


# ---------------------------------------------------------------------------
# load_order_model_map()
# ---------------------------------------------------------------------------

class TestLoadOrderModelMap:
    def test_builds_order_model_map(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [
            ["1001", "WFW5605MC", "TRUCK1"],
            ["1002", "MED6030MW", "TRUCK2"],
        ])
        result = load_order_model_map(path)
        assert result["1001"] == "WFW5605MC"
        assert result["1002"] == "MED6030MW"

    def test_skips_excluded_trucks(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [
            ["2001", "WFW5605MC", "STORAGE"],
            ["2002", "MED6030MW", "UNPAID"],
        ])
        result = load_order_model_map(path)
        assert "2001" not in result
        assert "2002" not in result

    def test_skips_service_codes(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [["3001", "X001", "TRUCK1"]])
        result = load_order_model_map(path)
        assert "3001" not in result

    def test_skips_delete_codes(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [["3002", "FREIGHT", "TRUCK1"]])
        result = load_order_model_map(path)
        assert "3002" not in result

    def test_stores_first_model_per_order(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [
            ["4001", "WFW5605MC", "TRUCK1"],
            ["4001", "MED6030MW", "TRUCK1"],
        ])
        result = load_order_model_map(path)
        assert result["4001"] == "WFW5605MC"

    def test_empty_xlsx_returns_empty_dict(self, tmp_path):
        path = make_batch_xlsx(tmp_path, [])
        result = load_order_model_map(path)
        assert result == {}


# ---------------------------------------------------------------------------
# dated_folder()
# ---------------------------------------------------------------------------

class TestDatedFolder:
    def test_creates_nested_structure(self, tmp_path, run_dt):
        result = dated_folder(tmp_path / "logs", run_dt)
        assert Path(result).exists()
        assert "2024" in result
        assert "JUNE" in result
        assert "20240615" in result

    def test_idempotent(self, tmp_path, run_dt):
        folder = tmp_path / "base"
        dated_folder(folder, run_dt)
        dated_folder(folder, run_dt)


# ---------------------------------------------------------------------------
# RunLogger
# ---------------------------------------------------------------------------

class TestRunLogger:
    def test_creates_log_file(self, logger):
        assert Path(logger.run_path).exists()

    def test_info_writes_to_log(self, logger):
        logger.info("test message")
        assert "test message" in Path(logger.run_path).read_text()

    def test_error_writes_to_log(self, logger):
        logger.error("something broke")
        content = Path(logger.run_path).read_text()
        assert "ERROR" in content
        assert "something broke" in content

    def test_result_success_not_added_to_failed(self, logger):
        logger.result("99", "SUCCESS")
        assert len(logger._failed_orders) == 0

    def test_result_failed_added_to_failed_orders(self, logger):
        logger.result("99", "FAILED", "upload error")
        assert ("99", "upload error") in logger._failed_orders

    def test_finalize_includes_mispick_counts(self, logger):
        logger.finalize({"SUCCESS": 1, "FAILED": 0, "MISPICK": 2, "MISRECEIVE": 1, "SKIPPED": 0})
        content = Path(logger.run_path).read_text()
        assert "MISPICK" in content
        assert "MISRECEIVE" in content

    def test_finalize_sends_email_on_failures(self, logger):
        logger._failed_orders = [("99", "some reason")]
        with patch("sync.send_failure_email") as mock_email:
            logger.finalize({"SUCCESS": 0, "FAILED": 1, "MISPICK": 0, "MISRECEIVE": 0, "SKIPPED": 0})
        mock_email.assert_called_once()

    def test_finalize_no_email_on_clean_run(self, logger):
        with patch("sync.send_failure_email") as mock_email:
            logger.finalize({"SUCCESS": 3, "FAILED": 0, "MISPICK": 0, "MISRECEIVE": 0, "SKIPPED": 0})
        mock_email.assert_not_called()


# ---------------------------------------------------------------------------
# send_failure_email()
# ---------------------------------------------------------------------------

class TestSendFailureEmail:
    def test_skips_when_not_configured(self, run_dt):
        with patch.object(sync, "EMAIL_FROM", ""), \
             patch.object(sync, "EMAIL_PASSWORD", ""), \
             patch.object(sync, "EMAIL_TO", ""):
            send_failure_email([("1", "err")], {}, run_dt, "/tmp/err.log")

    def test_sends_when_configured(self, run_dt):
        with patch.object(sync, "EMAIL_FROM", "from@example.com"), \
             patch.object(sync, "EMAIL_PASSWORD", "secret"), \
             patch.object(sync, "EMAIL_TO", "to@example.com"), \
             patch("smtplib.SMTP") as mock_smtp:
            instance = mock_smtp.return_value.__enter__.return_value
            send_failure_email([("1", "upload error")], {"FAILED": 1}, run_dt, "/tmp/err.log")
            instance.sendmail.assert_called_once()

    def test_email_includes_mispick_in_summary(self, run_dt):
        with patch.object(sync, "EMAIL_FROM", "from@example.com"), \
             patch.object(sync, "EMAIL_PASSWORD", "secret"), \
             patch.object(sync, "EMAIL_TO", "to@example.com"), \
             patch("smtplib.SMTP") as mock_smtp:
            instance = mock_smtp.return_value.__enter__.return_value
            send_failure_email(
                [("1", "mispick")],
                {"FAILED": 0, "MISPICK": 1, "MISRECEIVE": 0},
                run_dt, "/tmp/err.log"
            )
            body = instance.sendmail.call_args[0][2]
            assert "MISPICK" in body


# ---------------------------------------------------------------------------
# download_photos_for_item()
# ---------------------------------------------------------------------------

class TestDownloadPhotosForItem:
    def test_downloads_both_photos(self, logger, parsed_item, tmp_path):
        with patch("sync.mc.get_public_url", return_value="https://example.com/photo.jpg"), \
             patch("sync.mc.download_photo", return_value=True), \
             patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            paths = download_photos_for_item(parsed_item, logger)
        assert len(paths) == 2

    def test_skips_missing_asset_ids(self, logger, tmp_path):
        item = {"order_number": "1", "serial_asset_id": None, "id_asset_id": None}
        with patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            paths = download_photos_for_item(item, logger)
        assert paths == []

    def test_handles_failed_download(self, logger, parsed_item, tmp_path):
        with patch("sync.mc.get_public_url", return_value="https://example.com/photo.jpg"), \
             patch("sync.mc.download_photo", return_value=False), \
             patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            paths = download_photos_for_item(parsed_item, logger)
        assert paths == []

    def test_handles_missing_public_url(self, logger, parsed_item, tmp_path):
        with patch("sync.mc.get_public_url", return_value=None), \
             patch("tempfile.mkdtemp", return_value=str(tmp_path)):
            paths = download_photos_for_item(parsed_item, logger)
        assert paths == []


# ---------------------------------------------------------------------------
# process_completed_items() — QC gate integration
# ---------------------------------------------------------------------------

class TestProcessCompletedItems:
    @pytest.mark.asyncio
    async def test_success_path_clean_item(self, tmp_path, run_dt, order_model_map, clean_qc_result):
        parsed = {
            "order_number": "12345", "item_id": "abc",
            "serial_asset_id": "s1", "id_asset_id": "i1",
        }
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=clean_qc_result), \
             patch("sync.download_photos_for_item", return_value=["/tmp/photo.jpg"]), \
             patch("sync.upload_order_photos", new=AsyncMock(return_value=True)), \
             patch("sync.mc.mark_transferred") as mock_transfer:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_transfer.assert_called_once()

    @pytest.mark.asyncio
    async def test_mispick_skips_upload(self, tmp_path, run_dt, order_model_map):
        parsed = {"order_number": "12345", "item_id": "abc", "serial_asset_id": "s1", "id_asset_id": "i1"}
        mispick_result = {
            "status": "MISPICK", "item_id": "abc", "order_number": "12345",
            "inv_id": "INV001", "expected_model": "WFW5605MC",
            "model_extract": "WRONG", "label_model_extract": "WRONG",
            "notes": "Expected WFW5605MC but picked WRONG",
        }
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=mispick_result), \
             patch("sync.qc.update_status") as mock_status, \
             patch("sync.upload_order_photos", new=AsyncMock()) as mock_upload:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_upload.assert_not_called()
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_misreceive_skips_upload(self, tmp_path, run_dt, order_model_map):
        parsed = {"order_number": "12345", "item_id": "abc", "serial_asset_id": "s1", "id_asset_id": "i1"}
        misreceive_result = {
            "status": "MISRECEIVE", "item_id": "abc", "order_number": "12345",
            "inv_id": "INV001", "expected_model": "WFW5605MC",
            "model_extract": "WFW5605MC", "label_model_extract": "DIFFERENT",
            "notes": "Box WFW5605MC != label DIFFERENT",
        }
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=misreceive_result), \
             patch("sync.qc.update_status") as mock_status, \
             patch("sync.upload_order_photos", new=AsyncMock()) as mock_upload:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_upload.assert_not_called()
        mock_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_data_retries_next_cycle(self, tmp_path, run_dt, order_model_map):
        parsed = {"order_number": "12345", "item_id": "abc", "serial_asset_id": "s1", "id_asset_id": "i1"}
        no_data_result = {
            "status": "NO_DATA", "item_id": "abc", "order_number": "12345",
            "inv_id": "", "expected_model": "",
            "model_extract": "", "label_model_extract": "",
            "notes": "AI extraction columns are empty",
        }
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=no_data_result), \
             patch("sync.upload_order_photos", new=AsyncMock()) as mock_upload:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_items_with_no_photos(self, tmp_path, run_dt, order_model_map, clean_qc_result):
        parsed = {"order_number": "12345", "item_id": "abc", "serial_asset_id": None, "id_asset_id": None}
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=clean_qc_result), \
             patch("sync.upload_order_photos", new=AsyncMock()) as mock_upload:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_upload_not_marked_transferred(self, tmp_path, run_dt, order_model_map, clean_qc_result):
        parsed = {"order_number": "12345", "item_id": "abc", "serial_asset_id": "s1", "id_asset_id": "i1"}
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[{}]), \
             patch("sync.mc.parse_item", return_value=parsed), \
             patch("sync.qc.parse_item", return_value={}), \
             patch("sync.qc.check_item", return_value=clean_qc_result), \
             patch("sync.download_photos_for_item", return_value=["/tmp/photo.jpg"]), \
             patch("sync.upload_order_photos", new=AsyncMock(return_value=False)), \
             patch("sync.mc.mark_transferred") as mock_transfer:
            await sync.process_completed_items(run_dt, order_model_map)
        mock_transfer.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_board_no_errors(self, tmp_path, run_dt, order_model_map):
        with patch.object(sync, "LOG_BASE", tmp_path / "logs"), \
             patch.object(sync, "SCREEN_BASE", tmp_path / "screens"), \
             patch("sync.mc.get_completed_items", return_value=[]):
            await sync.process_completed_items(run_dt, order_model_map)
