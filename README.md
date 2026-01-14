# 🏦 Bank Statement PDF Scraper API

A robust, multi-bank PDF scraper exposed via a RESTful API. It uses intelligent coordinate-based extraction to parse bank statements into structured JSON data.

## Features

- **Multi-Bank Support**: Specialized layouts for **Union Bank** and **HDFC**.
- **API-First Design**: Built with FastAPI for easy integration.
- **Robust Extraction**:
    - Handles multi-line narrations.
    - Filters header/footer noise automatically.
    - Supports password-protected PDFs.
- **Clean Output**: JSON-formatted transaction records.

## Quick Start

### 1. Installation

```bash
pip install -r requirements.txt
```

### 2. Running the API Server

Start the production-ready FastAPI server using the provided `run.py` script:

```bash
python run.py
```

The server features:
- **Async Execution**: PDF processing runs in a background thread pool.
- **Structured Logging**: Real-time extraction logs in the console.
- **CORS Support**: Ready for frontend integration.

The API will be available at: `http://localhost:8002`

### 3. API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/extract` | Unified endpoint: Upload + Process + Result in one step. Required: `file`, `bank_key`. |
| `GET` | `/banks` | Get list of supported bank keys (e.g., `hdfc`, `union_bank`). |

### 4. Command Line Interface (CLI)

You can also run the scraper directly on a file without the API:

```bash
# Basic usage
python scraper.py "path/to/statement.pdf" --bank hdfc

# With password
python scraper.py "path/to/statement.pdf" --bank hdfc --pass "mypassword"
```

## Project Structure

```
pdf_scraper/
├── app/
│   ├── main.py             # FastAPI server entry point
│   ├── services/           # Core logic (Scraper Engine)
│   └── bank_layouts/       # Bank-specific configuration files
├── run.py                  # Easy-start script
├── requirements.txt        # Dependencies
├── uploads/                # Temporary storage for uploaded PDFs
└── outputs/                # Extracted JSON files
```

## Supported Banks

*   **HDFC Bank** (`hdfc`)
*   **Union Bank of India** (`union_bank`)

## Output Format

```json
[
  {
    "Date": "01/12/2025",
    "Narration": "NEFT DR-HDFC0000240-NETFLIX ENTERTAINMENT",
    "Chq./Ref.No.": "N33525246835",
    "ValueDt": "01/12/2025",
    "WithdrawalAmt": "649.00",
    "DepositAmt": "",
    "ClosingBalance": "12,450.00"
  }
]
```

## License

MIT
