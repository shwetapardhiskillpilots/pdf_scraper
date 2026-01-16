import re
    
# Layout configuration for Union Bank Statements
# Defined based on coordinate extraction from PDF layout analysis.

COLUMNS = {
    "Date": (0, 100),
    "Remarks": (100, 198),
    "Tran Id-1": (198, 278),
    "Instr. ID": (0, 0),         # Always empty for this bank format
    "UTR Number": (278, 450),
    "Withdrawals": (450, 545),
    "Deposits": (545, 642),
    "Balance": (642, 842)
}

# Fuzzy matching aliases for dynamic header detection
HEADER_ALIASES = {
    "Date": ["Date", "Txn Date"],
    "Remarks": ["Remarks", "Particulars", "Description"],
    "Tran Id-1": ["Tran Id", "Ref No", "Transaction ID"],
    "Instr. ID": ["Instr. ID", "Instrument"],
    "UTR Number": ["UTR Number", "UTR"],
    "Withdrawals": ["Withdrawals", "Debit"],
    "Deposits": ["Deposits", "Credit"],
    "Balance": ["Balance"]
}

# Standardized output keys
NORMALIZATION_MAP = {
    "Date": "date",
    "Remarks": "Remarks",
    "Tran Id-1": "Tran Id-1",
    "Instr. ID": "Instr. ID",
    "UTR Number": "UTR Number",
    "Withdrawals": "Withdrawal",
    "Deposits": "Deposit",
    "Balance": "balance"
}


PAGE_RULES = {
    "header_y_max": 250,
    "footer_y_min_ratio": 0.92,
    "continuation_gap": 45
}

TRANSACTION_START_KEYWORDS = ["rtgs", "epay", "neft:", "collection", "imps"]

DATE_PATTERN = re.compile(r'\d{2}[/-]\d{2}[/-]\d{2,4}')

NOISE_KEYWORDS = [
    "for any queries", "customer service", "this is a system generated",
    "no signature", "avail our loan", "missed call", "sms", "discrepancy",
    "page no", "union bank", "statement of account", "generated on",
    "missed call at", "uloan", "computer generated", "visit our website"
]

def clean_data(cat, val):
    """
    Sanitize and normalize field data.
    """
    if not val: return ""
    
    if cat == "Remarks":
        # Fix split words common in OCR
        for w in ["NETBANK", "PHONE", "HDFCBANK", "PAYMENT", "FROM", "COLLECTION"]:
            pattern = r'\s?'.join(list(w))
            val = re.sub(pattern, w, val, flags=re.I)
            
        # Join alphanumeric IDs split across lines
        # Heuristic: First part must end with a digit to avoid merging names (like STYLEMONK) with IDs
        val = re.sub(r'([A-Z0-9]{3,}[0-9])\s+([A-Z0-9]{8,})', r'\1\2', val)
        val = re.sub(r'([A-Z0-9]{8,}[0-9])\s+([A-Z0-9]{3,})', r'\1\2', val)

        # Fix known OCR misreads
        val = val.replace("ULTISTATECOOP", "MULTISTATE COOP")
        val = val.replace("SOLERPLY", "SOLAR SUPPLY")

        # Remove noise keywords
        for k in NOISE_KEYWORDS:
            val = re.sub(re.escape(k), "", val, flags=re.IGNORECASE)
            
        # Normalize whitespace and strip trailing punctuation
        val = re.sub(r'\s+', ' ', val).strip()
        val = re.sub(r'[,\-_\s]+$', '', val).strip()
        return val
        
    if cat in ["Withdrawals", "Deposits", "Balance"]:
        if any(c.isalpha() for c in val): return ""
        clean = re.sub(r'[^\d.,\-]', '', val)
        return clean.strip()
        
    if cat in ["Tran Id-1", "UTR Number", "Date"]:
        # Remove internal spaces in Ref Numbers (e.g. UTR / Sender No)
        if cat in ["Tran Id-1", "UTR Number"]:
            val = re.sub(r'\s+', '', val)
        return val.strip()
        
    return val.strip()

def post_process_record(record):
    """
    Union Bank specific normalization:
    - Handle cases where amounts bleed into the Balance column
    - Correct Debit/Credit direction based on keywords
    - Move 'Sender No' metadata to UTR field
    - Ensure final schema consistency
    """
    remarks = record.get("Remarks", "")
    withdrawals = record.get("Withdrawals", "")
    deposits = record.get("Deposits", "")
    balance = record.get("Balance", "")
    tran_id = record.get("Tran Id-1", "")
    utr = record.get("UTR Number", "")

    # Handle merged amount/balance columns (balance bleed)
    # If standard columns are empty, try to parse the amount from the balance field
    if not withdrawals and not deposits and balance:
        parts = re.findall(r'([0-9,.]+\.\d{2})', balance)
        if len(parts) >= 2:
            extracted_amt = parts[0]
            balance = balance[len(extracted_amt):].split("-")[-1].strip()
            if "-" in balance:
                balance = f"-{balance}"
            
            # Use keywords to determine if the bled amount is Dr or Cr
            dr_keywords = ["charges", "neftdr", "rtgsdr", "interest", "penal", "dr"]
            cr_keywords = ["neft", "rtgs", "cash", "loan", "cr"]
            rem_lower = remarks.lower()
            
            if any(k in rem_lower for k in dr_keywords):
                withdrawals = extracted_amt
            elif any(k in rem_lower for k in cr_keywords):
                deposits = extracted_amt
            else:
                # Default to withdrawals if direction is ambiguous
                withdrawals = extracted_amt

    # Extract metadata pattern "Sender No" and move it to UTR
    sender_match = re.search(r'Sender\s*No[:\s]*([A-Z0-9\s]+)', f"{tran_id} {remarks} {utr}", re.I)
    if sender_match:
        full_found = sender_match.group(0).strip()
        sender_val = sender_match.group(1).strip()
        # Remove internal spaces from Sender No
        sender_val_clean = re.sub(r'\s+', '', sender_val)
        utr = f"Sender No: {sender_val_clean}"
        # Clean it from other fields
        # Remove the full match from Remarks to be safe, but also specifically the ID if it was part of the messy merge
        remarks = remarks.replace(full_found, "").strip()
        remarks = remarks.replace(sender_val, "").strip() # Explicitly remove the ID part if 'Sender No' label was separated or lost
        tran_id = tran_id.replace(full_found, "").strip()

    # Final Cleanup
    tran_id = re.sub(r'\s+', '', tran_id)
    remarks = re.sub(r'\s+', ' ', remarks).strip()

    # Ensure balance doesn't contain amount spillover
    curr_amount = withdrawals or deposits
    if curr_amount and balance == curr_amount:
        balance = ""

    return {
        "Date": record.get("Date", ""),
        "Remarks": remarks,
        "Tran Id-1": tran_id,
        "Instr. ID": record.get("Instr. ID", ""),
        "UTR Number": utr,
        "Withdrawals": withdrawals,
        "Deposits": deposits,
        "Balance": balance
    }
