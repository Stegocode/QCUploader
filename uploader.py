import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

BASE_URL           = os.environ.get("PLATFORM_BASE_URL", "https://your-platform.example.com")
DEFAULT_SCREEN_DIR = os.environ.get("SCREENSHOT_DIR", str(Path.home() / "order_photo_sync" / "screenshots"))


async def screenshot(page, name, screen_dir=None):
    folder = screen_dir or DEFAULT_SCREEN_DIR
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".png")
    await page.screenshot(path=path)
    print(f"  Screenshot saved: {name}")


async def login(page, username, password, screen_dir=None):
    await page.goto(f"{BASE_URL}/login")
    await page.wait_for_load_state("networkidle")
    await page.fill("input[name='email']", username)
    await page.fill("input[name='password']", password)
    await page.press("input[name='password']", "Enter")
    await page.wait_for_load_state("networkidle")
    await screenshot(page, "01_after_login", screen_dir)
    print("  Login complete")


async def navigate_to_order(page, order_number, screen_dir=None):
    url = f"{BASE_URL}/sales/orders?OrderId={order_number}"
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    await screenshot(page, f"02_order_{order_number}", screen_dir)
    current_url = page.url
    is_invoice = "/sales/invoices/" in current_url
    print(f"  Navigated to order {order_number}" + (" [INVOICED]" if is_invoice else ""))
    return is_invoice


async def upload_photos(page, photo_paths, order_number, is_invoice=False, screen_dir=None):
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)
    await screenshot(page, "03_before_assets_click", screen_dir)

    btn = page.locator("#request-img-btn")
    await btn.scroll_into_view_if_needed()
    await btn.wait_for(state="visible", timeout=15000)
    await btn.click()
    await page.wait_for_timeout(3000)
    await screenshot(page, "04_after_assets_click", screen_dir)

    await page.click("a[href='#assets-content']")
    await page.wait_for_timeout(2000)
    await screenshot(page, "05_assets_tab", screen_dir)

    for i, photo_path in enumerate(photo_paths):
        print(f"  Uploading: {photo_path}")
        await page.click("button.k-add-button")
        await page.wait_for_timeout(2000)
        await screenshot(page, f"06_after_add_doc_{i}", screen_dir)
        await page.set_input_files("#S3URL", photo_path)
        await page.wait_for_timeout(2000)
        await screenshot(page, f"07_after_file_set_{i}", screen_dir)
        await page.click("button.k-grid-update")
        await page.wait_for_timeout(3000)
        await screenshot(page, f"08_after_update_{i}", screen_dir)

    await screenshot(page, "09_before_save", screen_dir)
    await page.click("#saveAsset")

    try:
        await page.wait_for_selector(".k-widget.k-window", state="hidden", timeout=15000)
    except Exception:
        await page.wait_for_timeout(6000)

    await screenshot(page, "10_after_save", screen_dir)
    print(f"  Saved {len(photo_paths)} photo(s) for order {order_number}")


async def upload_order_photos(username, password, order_number, photo_paths, screenshot_dir=None):
    """
    Main entry point. Launches a headless browser, logs in, navigates to the
    order, and uploads the provided photos to the assets panel.

    Args:
        username:       Platform login email
        password:       Platform login password
        order_number:   Order ID to navigate to
        photo_paths:    List of local file paths to upload
        screenshot_dir: Optional directory to save debug screenshots

    Returns:
        True on success, False on failure
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        try:
            await login(page, username, password, screenshot_dir)
            is_invoice = await navigate_to_order(page, order_number, screenshot_dir)
            await upload_photos(page, photo_paths, order_number, is_invoice, screenshot_dir)
            print(f"  Order {order_number} complete")
            return True
        except Exception as e:
            print(f"  ERROR on order {order_number}: {e}")
            await screenshot(page, f"error_{order_number}", screenshot_dir)
            return False
        finally:
            await browser.close()
