# Technical Documentation - Bank Statement PDF Scraper

## Overview
This system extracts transaction data from bank statement PDFs using **pdfplumber** for text extraction and **fuzzy matching** for intelligent column detection.

---

## Core Technologies Used

### 1. **pdfplumber** (Lines 29, 169-171)
- **What**: Python library for extracting text from PDFs
- **Why**: Gets the exact position (x, y coordinates) of every word in the PDF
- **How**: `page.extract_words()` returns a list of dictionaries with:
  - `text`: The actual word
  - `x0, y0`: Top-left corner coordinates
  - `x1, y1`: Bottom-right corner coordinates
  - `top`: Vertical position

### 2. **thefuzz** (Lines 31, 100-103)
- **What**: Fuzzy string matching library
- **Why**: Banks use different names for the same columns (e.g., "Debit" vs "Withdrawals")
- **How**: Scores similarity between strings (0-100%)
  - Example: "Withdrawal Amt." matches "Withdrawals" at 92%
  - We accept matches above 90% (Line 103)

### 3. **pandas** (Lines 30, 44)
- **What**: Data manipulation library
- **Why**: Converts our extracted data to Excel format
- **How**: `pd.DataFrame(data).to_excel()` creates XLSX files

---

## Architecture - Strategy Pattern

### Base Class: `BaseBankScraper` (Lines 33-281)
**Purpose**: Contains all the common logic that works for any bank statement

**Key Components**:

#### 1. Header Synonyms (Lines 41-48)
```python
self.header_synonyms = {
    "Date": ["Date", "Txn Date", "Transaction Date", ...],
    "Remarks": ["Remarks", "Description", "Narration", ...],
    ...
}
```
**Why**: Different banks use different column names. This maps them all to standard categories.

#### 2. Regex Patterns (Lines 54-55)
```python
self.date_pattern = re.compile(r'\d{2}[/-]\d{2}[/-]\d{2,4}')
self.time_pattern = re.compile(r'\d{2}:\d{2}(?::\d{2})?')
```
**Why**: To identify dates (01/11/25) and times (12:30:45) in the text

---

## Main Algorithm Flow

### Step 1: Header Detection (Lines 76-155)

**Function**: `identify_headers(page_words, page_width)`

**What it does**:
1. **Group words into lines** (Lines 82-91)
   - Words within 3 pixels vertically are on the same line
   - Sort each line left-to-right by x-coordinate

2. **Scan first 30 lines for headers** (Lines 108-109)
   - Skip noise lines (footers, page numbers)
   
3. **Group adjacent words into headers** (Lines 117-142)
   - Words within 9px horizontally → same header
   - Exception: "Instr. ID" allows 40px gap (Lines 133-135)
   - Don't merge if they're different categories (Line 127)

4. **Match headers to categories** (Lines 97-103)
   - Direct match: "Date" in text → "Date" category
   - Fuzzy match: "Txn Date" → "Date" category (90%+ similarity)

5. **Create column boundaries** (Lines 148-154)
   - Use **midpoints** between headers
   - First column starts at x=0
   - Last column ends at page width
   - **Why midpoints**: Gives wiggle room for slightly misaligned data

**Example**:
```
Header positions:
Date: x=40-56
Narration: x=144-178
Ref: x=284-328

Column boundaries created:
Date: 0 to 161 (midpoint of 56 and 144)
Narration: 161 to 256 (midpoint of 178 and 284)
Ref: 256 to page_width
```

---

### Step 2: Data Extraction (Lines 157-281)

**Function**: `extract_data(pdf_path, known_password)`

#### Phase 1: PDF Opening (Lines 162-177)
```python
# Try without password first
pdf = pdfplumber.open(pdf_path)

# If that fails and we have a password, try with it
if known_password:
    pdf = pdfplumber.open(pdf_path, password=known_password)

# If still fails, ask user for password
pdf = pdfplumber.open(pdf_path, password=self.get_password(pdf_path))
```

#### Phase 2: Process Each Page (Lines 189-273)

**Line-by-line processing**:

1. **Group words into lines** (Lines 197-207)
   - Same as header detection
   - Words within 3px vertically = same line

2. **Skip header row** (Lines 211-212)
   ```python
   if line[0]['top'] <= header_y + 5: continue
   ```

3. **Filter noise** (Lines 215-217)
   ```python
   if self.is_line_noise(text) and not self.is_transaction_start(line, text):
       continue
   ```
   - Skip footers like "Page No: 1"
   - BUT keep it if it's actually a transaction (has date at start)

4. **Assign words to columns** (Lines 223-232)
   ```python
   for w in line:
       for c in column_layout:
           overlap = min(w['x1'], c['x1']) - max(w['x0'], c['x0'])
           if overlap > max_ov:
               best_col = c['name']
   ```
   **How it works**: Calculate how much the word overlaps with each column, assign to the one with maximum overlap

5. **Detect transaction start** (Lines 248-249)
   ```python
   first_word = line[0]['text'].strip()
   if self.date_pattern.match(first_word) and line[0]['x0'] < 100:
       return True
   ```
   **Logic**: A new transaction MUST have:
   - A date as the first word
   - Date must be at far left (x < 100 pixels)

6. **Handle multi-line transactions** (Lines 251-273)
   
   **If it's a NEW transaction** (Lines 252-260):
   ```python
   if current_record:
       out_data.append(current_record)  # Save previous
   current_record = flat  # Start new one
   ```

   **If it's a CONTINUATION** (Lines 261-273):
   ```python
   if current_record and gap < 20:  # Within 20px vertically
       # Merge into current record
       current_record[remarks_col] += " " + spill
   ```
   **Why gap < 20**: Prevents merging footers that are far below

#### Phase 3: Cross-Page Handling (Lines 275-279)

**CRITICAL FIX** (Lines 275-276):
```python
# Don't reset current_record here!
# Transactions can span across pages
```

**Before fix**:
```python
if current_record:
    out_data.append(current_record)
    current_record = None  # ❌ This broke cross-page transactions
```

**After fix**:
```python
# Don't reset - let it continue to next page
# Only save at the very end (Lines 277-279)
if current_record:
    out_data.append(current_record)
```

---

## Bank-Specific Scrapers

### UnionBankScraper (Lines 283-300)
**Extends**: BaseBankScraper

**Customization**: Aggressive noise filtering (Lines 287-295)
```python
self.noise_keywords = [
    "avail our loan", "missed call", "sms <uloan>", ...
]
```

**Special logic** (Lines 298-300):
```python
promo_words = ["avail", "loan", "products", "missed", "call"]
if sum(1 for pw in promo_words if pw in lt) >= 2:
    return True  # It's noise if 2+ promotional words
```

### HDFCBankScraper (Lines 302-315)
**Extends**: BaseBankScraper

**Customization**: Simpler noise filter (Lines 306-310)
- HDFC statements are cleaner
- Only basic footer filtering needed

---

## Gradio Web Interface (app.py)

### Main Function: `process_statement` (Lines 7-51)

**Flow**:
1. **Get scraper** (Lines 12-22)
   ```python
   bank_map = {"Union Bank": "union_bank", ...}
   scraper = factory.get_scraper(internal_bank)
   ```

2. **Extract data** (Line 25)
   ```python
   data = scraper.extract_data(pdf_path, known_password=password)
   ```

3. **Create preview** (Line 31)
   ```python
   json_preview = json.dumps(data, indent=2)
   ```

4. **Save files** (Lines 37-45)
   ```python
   json_output = "outputs/{filename}_output.json"
   xlsx_output = "outputs/{filename}_output.xlsx"
   ```

### UI Layout (Lines 54-95)

**Three columns**:
1. **Inputs** (Lines 59-67): File upload, bank dropdown, password
2. **Preview** (Lines 69-76): Status + JSON preview
3. **Downloads** (Lines 78-80): JSON and Excel download buttons

**Button wiring** (Lines 82-86):
```python
process_btn.click(
    fn=process_statement,
    inputs=[file_input, bank_dropdown, password_input],
    outputs=[status_output, json_preview, json_file, excel_file]
)
```

---

## Key Algorithms Explained

### 1. Midpoint Column Boundaries (Lines 148-154)
**Problem**: Data might not align perfectly with headers
**Solution**: Use midpoint between headers as boundary
```
Header A ends at x=100
Header B starts at x=200
Boundary = (100 + 200) / 2 = 150
```
**Benefit**: Data at x=140 or x=160 both go to correct column

### 2. Gap-Based Merging (Line 261)
**Problem**: How to know if a line continues the previous transaction?
**Solution**: Check vertical gap
```python
if gap < 20:  # Within 20 pixels
    # It's a continuation
else:
    # Too far, probably footer
```

### 3. Fuzzy Header Matching (Lines 100-103)
**Problem**: "Withdrawal Amt." vs "Withdrawals" - same meaning, different text
**Solution**: Calculate similarity score
```python
match, score = process.extractOne(txt, synonyms, scorer=fuzz.partial_ratio)
if score > 90:  # 90% similar
    return category
```

---

## Output Format

### JSON Structure
```json
[
  {
    "Date": "01/11/25 14:23:38",
    "Narration": "UPI-MERCHANT NAME",
    "Chq./Ref.No.": "0000253058699453",
    "WithdrawalAmt.": "708.00",
    "DepositAmt.": "",
    "ClosingBalance": "2,665,907.49"
  }
]
```

### Excel Structure
Same data in tabular format with columns

---

## Error Handling

1. **Password-protected PDFs** (Lines 162-177): Try without password → try with known password → ask user
2. **Missing headers** (Lines 180-182): Return empty if can't find at least 3 columns
3. **Exceptions** (Lines 280-282): Catch all errors, print message, return empty list

---

## Performance Optimizations

1. **Early exit on noise** (Lines 215-217): Skip processing footer lines
2. **Limit header scan** (Line 108): Only check first 30 lines for headers
3. **Overlap calculation** (Lines 228-231): O(n*m) where n=words, m=columns (acceptable for small m)

---

## Testing & Verification

**Union Bank**: 22 transactions extracted
**HDFC**: 86 transactions extracted
**Cross-page transactions**: Verified working (14-11-2025 transaction)
