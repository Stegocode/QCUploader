# QCUploader

A full warehouse operations automation suite that detects pick and receive errors, syncs photos, and populates delivery boards — built on top of Monday.com and a web-based order management platform.

---

## What It Does

Every day, warehouse pickers pull appliances for tomorrow's deliveries and photograph each unit — one photo of the model/serial number on the box, one photo of the internal inventory label. Monday.com's AI extracts the model and serial data from those photos automatically.

QCUploader runs in the background and does three things:

1. **Populates** tomorrow's delivery orders into Monday.com each morning
2. **Catches errors** all day — comparing what was picked against what was ordered
3. **Uploads** the photos to the order management platform for clean, verified picks

If a picker grabbed the wrong model, it gets flagged as a **MISPICK** before it ever reaches the customer. If a unit was received into inventory incorrectly, it gets flagged as a **MISRECEIVE**. Only verified picks get uploaded.

---

## Daily Flow

```
MORNING (run once)
──────────────────────────────────────────────────────
run_populator.py
  └── Scrapes batch invoice for tomorrow's deliveries
  └── Parses orders → model numbers
  └── Creates Monday items in delivery group
  └── Saves batch invoice to DOWNLOAD_DIR (shared inbox)

ALL DAY (every 30 minutes)
──────────────────────────────────────────────────────
sync.py polling loop
  ├── Loads batch invoice from DOWNLOAD_DIR
  ├── Fetches completed items from Monday
  │
  ├── mispick_checker.py (gate)
  │     ├── Reads AI-extracted columns from Monday
  │     ├── Compares model extract vs batch invoice model
  │     │     └── Mismatch → MISPICK status, skip upload
  │     └── Compares box model extract vs label model extract
  │           └── Mismatch → MISRECEIVE status, skip upload
  │
  └── uploader.py (clean items only)
        └── Logs into platform via headless browser
        └── Navigates to order
        └── Uploads photos to assets panel
        └── Marks item as transferred in Monday
```

---

## The Tools

Each module works as a standalone tool and as part of the full suite.

### `monday_populator.py`
Scrapes the batch invoice from the order management platform for the next business day, parses all orders and model numbers, and creates the corresponding items in Monday.com. Runs once each morning.

```bash
python run_populator.py
```

### `mispick_checker.py`
Reads Monday.com AI-extracted photo data and compares it against the batch invoice to detect two error types:

| Flag | Condition |
|------|-----------|
| `MISPICK` | Picked model ≠ ordered model |
| `MISRECEIVE` | Box model ≠ inventory label model |

Flagged items have their Monday status updated automatically and are skipped by the uploader.

```bash
python run_mispick.py --serial path/to/serial-number-inventory.csv
```

### `uploader.py`
Headless browser automation that logs into the order management platform and uploads photos to order asset panels. Only receives clean, verified picks from the sync loop.

### `sync.py`
The main orchestrator. Polls Monday.com every 30 minutes, runs the mispick gate on each completed item, uploads clean items, and sends failure email notifications if uploads fail.

```bash
python sync.py
```

### `monday_client.py`
Monday.com API client shared across all tools. Handles fetching items, resolving asset URLs, downloading photos, and updating statuses.

---

## Shared Inbox

The batch invoice is the shared artifact that ties the suite together.

```
DOWNLOAD_DIR/
└── bulk-invoice-XXXXXX.xlsx   ← written by populator, read by sync all day
```

Set `DOWNLOAD_DIR` in your `.env`. All tools read from the same location — no rescraping, no redundant browser sessions.

---

## Setup

### Requirements

```bash
pip install playwright selenium openpyxl python-dotenv requests pytest pytest-asyncio
playwright install chromium
```

### Environment

```bash
cp .env.example .env
# Fill in all values — see .env.example for full reference
```

### Running the full suite

**Morning:**
```bash
python run_populator.py
```

**All day (keep running):**
```bash
python sync.py
```

**Standalone mispick check (optional):**
```bash
python run_mispick.py --serial path/to/serial-number-inventory.csv
```

---

## Running Tests

```bash
pytest tests/ -v
```

All tests mock external dependencies — no live platform or Monday.com connection needed. 60+ tests covering every module.

---

## Project Structure

```
QCUploader/
├── uploader.py            # Headless browser photo uploader
├── sync.py                # Main polling orchestrator
├── monday_client.py       # Monday.com API client
├── monday_populator.py    # Batch invoice scraper + Monday board populator
├── mispick_checker.py     # Pick and receive error detection
├── run_populator.py       # Entry point — morning run
├── run_mispick.py         # Entry point — standalone mispick check
├── .env.example           # Environment variable reference
├── tests/
│   ├── test_uploader.py
│   ├── test_sync.py
│   ├── test_monday_client.py
│   ├── test_monday_populator.py
│   └── test_mispick_checker.py
└── README.md
```

---

## Error Types

| Status | Meaning | Action |
|--------|---------|--------|
| `OK` | All checks passed | Photo uploaded to platform |
| `MISPICK` | Wrong model picked for order | Flagged in Monday, upload skipped |
| `MISRECEIVE` | Box model ≠ inventory label | Flagged in Monday, upload skipped |
| `BOTH` | Mispick and misreceive | Both flags set, upload skipped |
| `NO_DATA` | AI extraction not yet complete | Skipped, retried next cycle |
| `NO_MATCH` | Order not found in batch invoice | Logged, upload skipped |

---

## License

MIT License — see LICENSE file.
