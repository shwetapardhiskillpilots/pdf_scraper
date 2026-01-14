import re
    
# Layout configuration for HDFC Bank Statements
# Defined based on coordinate extraction from PDF layout analysis.

FRIENDLY_NAME = "HDFC"

COLUMNS = {
    # X-coordinates for column boundaries
    "Date": (0, 68),             
    "Narration": (68, 260),      
    "Chq./Ref.No.": (260, 350),  
    "ValueDt": (350, 410),       
    "WithdrawalAmt": (410, 490),
    "DepositAmt": (490, 560),
    "ClosingBalance": (560, 850)
}

# Fuzzy matching aliases for dynamic header detection
HEADER_ALIASES = {
    "Date": ["Date", "Txn Date", "date"],
    "Narration": ["Narration", "Description", "Particulars", "narration"],
    "Chq./Ref.No.": ["Chq./Ref.No.", "Ref No", "Cheque No", "Reference"],
    "ValueDt": ["Value Dt", "Value Date"],
    "WithdrawalAmt": ["Withdrawal Amt", "Debit", "Withdrawal"],
    "DepositAmt": ["Deposit Amt", "Credit", "Deposit"],
    "ClosingBalance": ["Closing Balance", "Balance", "closingbalance"]
}

# Standardized output keys
NORMALIZATION_MAP = {
    "Date": "date",
    "Narration": "Narration",
    "Chq./Ref.No.": "Chq./Ref.No.",
    "ValueDt": "ValueDt",
    "WithdrawalAmt": "Withdraw",
    "DepositAmt": "Deposit",
    "ClosingBalance": "ClosingBalance"
}

PAGE_RULES = {
    "header_y_max": 200,          # Skip header information in the top region
    "footer_y_min_ratio": 0.90,   # Ignore footer text (disclaimers, etc.)
    "continuation_gap": 40        # Merge lines if they are vertically close
}

TRANSACTION_START_KEYWORDS = ["rtgs", "imps", "upi", "neft", "chqdep"]

# Standard HDFC date format (DD/MM/YY)
DATE_PATTERN = re.compile(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}')

NOISE_KEYWORDS = [
    "closing balance includes", "closingbalanceincludes",
    "contents of this statement", "contentsofthisstatement",
    "registered office", "registeredoffice",
    "gstin", "generated on", "requesting branch",
    "this is a computer generated", "thisisacomputergenerated",
    "page no", "hdfc bank", "hdfcbank", "stateaccountreceipt",
    "fundsearmarked", "statutorydisclaimer", "disclaimer"
]

def clean_data(cat, val):
    """
    Sanitize and normalize the field data.
    """
    if not val: return ""
    
    if cat == "Narration":
        # Fix split words common in OCR (e.g., NETB ANK -> NETBANK)
        for w in ["NETBANK", "PHONE", "HDFCBANK", "PAYMENT", "FROM"]:
            pattern = r'\s?'.join(list(w))
            val = re.sub(pattern, w, val, flags=re.I)
        
        # Join alphanumeric IDs split across lines (e.g. 6202 5111 -> 62025111)
        # We ensure at least one part is long enough to avoid false positives.
        val = re.sub(r'([A-Z0-9]{3,})\s+([A-Z0-9]{8,})', r'\1\2', val)
        val = re.sub(r'([A-Z0-9]{8,})\s+([A-Z0-9]{3,})', r'\1\2', val)

        # Fix known OCR misreads
        val = val.replace("ULTISTATECOOP", "MULTISTATE COOP")
        val = val.replace("SOLERPLY", "SOLAR SUPPLY")
        
        # Remove any known noise phrases that slipped through line filtering
        for k in NOISE_KEYWORDS:
            val = re.sub(re.escape(k), "", val, flags=re.IGNORECASE)
        
        # Truncate if we hit footer text
        if "RegisteredOffice" in val or "HDFCBankHouse" in val or "*Closingbalance" in val:
            val = re.split(r'RegisteredOffice|HDFCBankHouse|\*Closingbalance', val, flags=re.I)[0]
            
        # Normalize whitespace and strip trailing punctuation
        val = re.sub(r'\s+', ' ', val).strip()
        val = re.sub(r'[,\-_\s]+$', '', val)
        
        return val
        
    if cat in ["WithdrawalAmt", "DepositAmt", "ClosingBalance"]:
        # If it contains letters, it's likely noise/header, not an amount.
        if any(c.isalpha() for c in val): return ""
        clean = re.sub(r'[^\d.,]', '', val)
        return clean.strip()
        
    if cat == "Chq./Ref.No.":
        # Remove metadata prefixes
        val = re.sub(r'(GeneratedBy|RequestingBranchCode).*', '', val, flags=re.IGNORECASE)
        val = re.sub(r'[,\-_\s]+$', '', val)
        # Reference numbers should not have spaces
        val = re.sub(r'\s+', '', val)
        return val.strip()
        
    return val.strip()

def post_process_record(record):
    """
    Final data integrity checks.
    """
    dt = record.get("Date", "")
    vdt = record.get("ValueDt", "")
    
    # Ensure Date and Value Date are synchronized if one is missing
    if dt and not vdt:
        record["ValueDt"] = dt
    elif vdt and not dt:
        record["Date"] = vdt
        
    return record
