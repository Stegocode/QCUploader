"""
Tests for uploader.py

Mocks the Playwright page object so no browser is launched during testing.
Run with: pytest tests/test_uploader.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
import uploader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_page():
    """A fully mocked Playwright page object."""
    page = AsyncMock()
    page.url = "https://your-platform.example.com/sales/orders/12345"
    return page


# ---------------------------------------------------------------------------
# screenshot()
# ---------------------------------------------------------------------------

class TestScreenshot:
    @pytest.mark.asyncio
    async def test_creates_directory_and_saves(self, mock_page, tmp_path):
        await uploader.screenshot(mock_page, "test_shot", screen_dir=str(tmp_path))
        mock_page.screenshot.assert_called_once()
        call_kwargs = mock_page.screenshot.call_args[1]
        assert "test_shot.png" in call_kwargs["path"]

    @pytest.mark.asyncio
    async def test_uses_default_dir_when_none_provided(self, mock_page, tmp_path):
        with patch.object(uploader, "DEFAULT_SCREEN_DIR", str(tmp_path)):
            await uploader.screenshot(mock_page, "default_shot")
        mock_page.screenshot.assert_called_once()


# ---------------------------------------------------------------------------
# login()
# ---------------------------------------------------------------------------

class TestLogin:
    @pytest.mark.asyncio
    async def test_navigates_fills_and_submits(self, mock_page, tmp_path):
        await uploader.login(mock_page, "user@example.com", "secret", screen_dir=str(tmp_path))

        mock_page.goto.assert_called_once_with(f"{uploader.BASE_URL}/login")
        mock_page.fill.assert_any_call("input[name='email']", "user@example.com")
        mock_page.fill.assert_any_call("input[name='password']", "secret")
        mock_page.press.assert_called_once_with("input[name='password']", "Enter")

    @pytest.mark.asyncio
    async def test_waits_for_network_idle_twice(self, mock_page, tmp_path):
        await uploader.login(mock_page, "u", "p", screen_dir=str(tmp_path))
        calls = [c.args[0] for c in mock_page.wait_for_load_state.call_args_list]
        assert calls.count("networkidle") == 2


# ---------------------------------------------------------------------------
# navigate_to_order()
# ---------------------------------------------------------------------------

class TestNavigateToOrder:
    @pytest.mark.asyncio
    async def test_returns_false_for_regular_order(self, mock_page, tmp_path):
        mock_page.url = "https://your-platform.example.com/sales/orders/99"
        result = await uploader.navigate_to_order(mock_page, 99, screen_dir=str(tmp_path))
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_for_invoiced_order(self, mock_page, tmp_path):
        mock_page.url = "https://your-platform.example.com/sales/invoices/99"
        result = await uploader.navigate_to_order(mock_page, 99, screen_dir=str(tmp_path))
        assert result is True

    @pytest.mark.asyncio
    async def test_navigates_to_correct_url(self, mock_page, tmp_path):
        await uploader.navigate_to_order(mock_page, 42, screen_dir=str(tmp_path))
        mock_page.goto.assert_called_once_with(f"{uploader.BASE_URL}/sales/orders?OrderId=42")


# ---------------------------------------------------------------------------
# upload_photos()
# ---------------------------------------------------------------------------

class TestUploadPhotos:
    @pytest.mark.asyncio
    async def test_uploads_each_photo(self, mock_page, tmp_path):
        photos = ["/tmp/photo1.jpg", "/tmp/photo2.jpg"]
        await uploader.upload_photos(mock_page, photos, order_number=1, screen_dir=str(tmp_path))

        set_input_calls = mock_page.set_input_files.call_args_list
        assert len(set_input_calls) == 2
        assert set_input_calls[0].args == ("#S3URL", "/tmp/photo1.jpg")
        assert set_input_calls[1].args == ("#S3URL", "/tmp/photo2.jpg")

    @pytest.mark.asyncio
    async def test_empty_photo_list(self, mock_page, tmp_path):
        await uploader.upload_photos(mock_page, [], order_number=1, screen_dir=str(tmp_path))
        mock_page.set_input_files.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_button_always_clicked(self, mock_page, tmp_path):
        await uploader.upload_photos(mock_page, ["/tmp/a.jpg"], order_number=1, screen_dir=str(tmp_path))
        click_calls = [c.args[0] for c in mock_page.click.call_args_list]
        assert "#saveAsset" in click_calls


# ---------------------------------------------------------------------------
# upload_order_photos() — integration-level, browser fully mocked
# ---------------------------------------------------------------------------

class TestUploadOrderPhotos:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, tmp_path):
        with patch("uploader.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_page.url = "https://your-platform.example.com/sales/orders/1"

            mock_pw.return_value.__aenter__.return_value.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)

            result = await uploader.upload_order_photos("u", "p", 1, ["/tmp/a.jpg"], screenshot_dir=str(tmp_path))
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, tmp_path):
        with patch("uploader.async_playwright") as mock_pw:
            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_page = AsyncMock()
            mock_page.goto.side_effect = Exception("Network error")

            mock_pw.return_value.__aenter__.return_value.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_context.new_page = AsyncMock(return_value=mock_page)

            result = await uploader.upload_order_photos("u", "p", 1, [], screenshot_dir=str(tmp_path))
            assert result is False
