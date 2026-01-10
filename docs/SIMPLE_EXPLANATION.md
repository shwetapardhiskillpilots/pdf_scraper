# Simple Explanation - Bank Statement PDF Scraper

## What This Project Does

This tool reads bank statement PDFs and extracts all transaction data into Excel/JSON files automatically.

**Input**: Bank statement PDF (Union Bank or HDFC)
**Output**: Clean Excel file with all transactions

---

## What We Used

### 1. **pdfplumber** - The PDF Reader
- **What it does**: Reads text from PDFs and tells us exactly where each word is positioned
- **Why we need it**: To know which column each piece of data belongs to
- **Example**: It tells us "708.00" is at position x=410, so we know it's in the "Withdrawals" column

### 2. **thefuzz** - The Smart Matcher
- **What it does**: Matches similar words even if they're spelled differently
- **Why we need it**: Different banks use different names for the same thing
- **Example**: "Debit" and "Withdrawals" mean the same thing - thefuzz recognizes this

### 3. **pandas** - The Excel Maker
- **What it does**: Converts our data into Excel files
- **Why we need it**: To give users a nice Excel file they can open

### 4. **Gradio** - The Web Interface
- **What it does**: Creates a simple website where users can upload PDFs
- **Why we need it**: So users don't need to use command line

---

## How It Works (Simple Steps)

### Step 1: Find the Headers
```
The PDF has a header row like:
Date | Narration | Withdrawals | Deposits | Balance

We scan the first page to find this row and remember where each column is.
```

### Step 2: Read Each Line
```
For each line below the header:
- Check if it's a new transaction (starts with a date)
- Or if it's a continuation of the previous transaction
- Assign each word to the correct column based on its position
```

### Step 3: Handle Special Cases

**Multi-line transactions:**
```
Sometimes one transaction is split across multiple lines:
Line 1: 01/11/25  UPI-MERCHANT
Line 2:           NAME-CONTINUED  708.00

We merge these into one transaction.
```

**Cross-page transactions:**
```
Sometimes a transaction starts on page 1 and continues on page 2.
We keep track and merge them correctly.
```

**Noise filtering:**
```
We skip footer text like:
- "Page No: 1"
- "For any queries call..."
- "Avail our loan products..."
```

### Step 4: Save the Results
```
Save as:
- JSON file (for programs to read)
- Excel file (for humans to read)
```

---

## The Smart Parts

### 1. Midpoint Column Boundaries
**Problem**: Data might not align perfectly with headers

**Solution**: Instead of using exact header positions, we use the midpoint between headers
```
Header "Date" ends at x=100
Header "Narration" starts at x=200
We set the boundary at x=150 (middle)

So data at x=140 or x=160 both go to the right column
```

### 2. Gap-Based Merging
**Problem**: How do we know if a line continues the previous transaction?

**Solution**: Check the vertical gap
```
If gap < 20 pixels → It's a continuation, merge it
If gap > 20 pixels → It's probably a footer, skip it
```

### 3. Bank-Specific Rules
**Problem**: Different banks have different junk text

**Solution**: Each bank has its own scraper class
```
UnionBankScraper → Filters "Avail our loan" messages
HDFCBankScraper → Filters "Customer care" messages
```

---

## File Structure

```
scraper.py (Main file)
├── BaseBankScraper (Works for any bank)
│   ├── identify_headers() → Finds columns
│   └── extract_data() → Extracts transactions
│
├── UnionBankScraper (Union Bank specific)
│   └── is_line_noise() → Filters Union Bank junk
│
└── HDFCBankScraper (HDFC specific)
    └── is_line_noise() → Filters HDFC junk

app.py (Web interface)
└── process_statement() → Handles file upload and calls scraper
```

---

## Key Algorithms Explained Simply

### Algorithm 1: Header Detection
```
1. Look at the first 30 lines of the PDF
2. For each line, group words that are close together
3. Check if these words match our known column names
4. The line with the most matches is the header
5. Remember the position of each column
```

### Algorithm 2: Word-to-Column Assignment
```
For each word in a line:
1. Check which column it overlaps with the most
2. Assign it to that column

Example:
Word "708.00" is at x=410
- Overlaps with "Narration" column: 0 pixels
- Overlaps with "Withdrawals" column: 32 pixels ✓
- Overlaps with "Deposits" column: 0 pixels

Assign to "Withdrawals"
```

### Algorithm 3: Transaction Detection
```
A new transaction starts when:
1. The line has a date (like 01/11/25)
2. The date is at the very beginning (far left)

Otherwise, it's a continuation of the previous transaction.
```

---

## What Makes It Work Well

### 1. Flexible Column Boundaries
- Uses midpoints instead of exact positions
- Handles slightly misaligned data

### 2. Smart Merging
- Merges multi-line transactions correctly
- Doesn't merge footer text

### 3. Cross-Page Support
- Keeps transactions alive across pages
- Saves only at the very end

### 4. Fuzzy Matching
- Recognizes "Debit" = "Withdrawals"
- Works with different bank formats

---

## Results

**Union Bank Statement:**
- Input: 2-page PDF
- Output: 22 transactions extracted
- Time: ~2 seconds

**HDFC Statement:**
- Input: Multi-page encrypted PDF
- Output: 86 transactions extracted
- Time: ~3 seconds

---

## How to Use

### Web Interface (Easy)
```bash
1. Run: python app.py
2. Open browser to http://127.0.0.1:7860
3. Upload PDF
4. Select bank
5. Download Excel file
```

### Command Line (Advanced)
```bash
python scraper.py statement.pdf --bank=union_bank
```

---

## Summary

**What we built**: A smart PDF scraper that extracts bank transactions

**How it works**: 
1. Find column positions
2. Read each line
3. Assign words to columns
4. Merge multi-line data
5. Filter out junk
6. Save to Excel

**Why it's smart**:
- Handles different bank formats
- Works with messy PDFs
- Merges split transactions
- Filters noise automatically

**Technologies**: pdfplumber (reading), thefuzz (matching), pandas (Excel), gradio (web UI)
