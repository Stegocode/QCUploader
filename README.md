# OrderPhotoSync

A headless browser automation tool that uploads photos to order records in web-based warehouse management platforms. Built with Playwright and Python.

## What it does

Given an order number and a list of local image paths, OrderPhotoSync will:

1. Log into the platform
2. Navigate to the order record
3. Open the assets panel
4. Upload each photo
5. Save and close

Handles both standard orders and invoiced orders automatically.

## Requirements

- Python 3.9+
- [Playwright](https://playwright.dev/python/)
- `python-dotenv`
- `pytest` + `pytest-asyncio` (for tests)

```bash
pip install playwright python-dotenv pytest pytest-asyncio
playwright install chromium
```

## Setup

```bash
cp .env.example .env
# Edit .env with your platform URL and credentials
```

## Usage

```python
import asyncio
from uploader import upload_order_photos

asyncio.run(upload_order_photos(
    username="your@email.com",
    password="yourpassword",
    order_number=12345,
    photo_paths=["/path/to/photo1.jpg", "/path/to/photo2.jpg"],
))
```

## Running tests

```bash
pytest tests/ -v
```

All tests mock the Playwright browser — no live platform connection needed.

## Project structure

```
order_photo_sync/
├── uploader.py          # Core automation logic
├── .env.example         # Environment variable template
├── tests/
│   └── test_uploader.py # Full pytest suite
└── README.md
```
