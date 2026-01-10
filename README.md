# 🏦 Bank Statement PDF Scraper

A robust, multi-bank PDF scraper that extracts transaction data from bank statements with high accuracy using intelligent fuzzy matching and layout analysis.

## Features

- **Multi-Bank Support**: Specialized scrapers for Union Bank, HDFC, and generic formats
- **Smart Header Detection**: Uses fuzzy matching to identify columns even with variations
- **Multi-Line Handling**: Correctly merges continuation lines and narration text
- **Noise Filtering**: Removes promotional text and footer information
- **Web Interface**: User-friendly Gradio UI with JSON preview
- **Multiple Export Formats**: JSON and Excel (XLSX) outputs

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Web Interface

```bash
python app.py
```

Then open your browser to `http://127.0.0.1:7860`

### Command Line

```bash
# Union Bank
python scraper.py sample_pdfs/your_statement.pdf --bank=union_bank

# HDFC (with password)
python scraper.py sample_pdfs/your_statement.pdf --bank=hdfc --pass=YOUR_PASSWORD

# Generic/Auto-detect
python scraper.py sample_pdfs/your_statement.pdf --bank=generic
```

## Project Structure

```
pdf_scraper/
├── app.py              # Gradio web interface
├── scraper.py          # Core scraper logic with bank-specific implementations
├── requirements.txt    # Python dependencies
├── sample_pdfs/        # Sample bank statement PDFs
├── outputs/            # Generated JSON and Excel files
└── docs/              # Documentation
```

## Supported Banks

- **Union Bank**: Credit card statements with specialized noise filtering
- **HDFC**: Account statements with password support
- **Generic**: Works with most standard bank statement formats

## How It Works

1. **pdfplumber** extracts text with precise coordinates
2. **Fuzzy matching** identifies column headers intelligently
3. **Bank-specific scrapers** apply custom noise filters and rules
4. **Multi-line merging** combines continuation text correctly
5. **Export** to JSON and Excel formats

## Output Format

```json
[
  {
    "Date": "01/11/25",
    "Narration": "Transaction description",
    "Withdrawals": "708.00",
    "Deposits": "",
    "Balance": "2,665,907.49"
  }
]
```

## License

MIT
