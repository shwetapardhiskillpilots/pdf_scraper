import sys
import subprocess
import importlib
import os
import re
import json
import getpass

# Automatic Dependency Installation
def install_and_import(package, import_name=None):
    if import_name is None:
        import_name = package
    try:
        importlib.import_module(import_name)
    except ImportError:
        print(f"Installing missing package: {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"Successfully installed {package}.")
        except Exception as e:
            print(f"Failed to install {package}. Error: {e}")
            sys.exit(1)

# Ensure dependencies are installed before importing
install_and_import("pdfplumber")
install_and_import("pandas")
install_and_import("thefuzz")

import pdfplumber
import pandas as pd
from thefuzz import process, fuzz

class BankStatementScraper:
    def __init__(self):
        # Master list of standard column types we want to detect
        self.target_headers = ["Date", "Remarks", "Withdrawals", "Deposits", "Balance", "RefNo"]
        
        # Valid semantic synonyms for each target
        self.header_synonyms = {
            "Date": ["Date", "Txn Date", "Transaction Date", "Value Date", "Date of Txn"],
            "Remarks": ["Remarks", "Description", "Narration", "Particulars", "Transaction Details", "Details"],
            "Withdrawals": ["Withdrawals", "Debit", "Dr", "Withdrawal Amt", "Debit Amount"],
            "Deposits": ["Deposits", "Credit", "Cr", "Deposit Amt", "Credit Amount"],
            "Balance": ["Balance", "Bal", "Closing Balance", "Net Balance"],
            "RefNo": ["Ref No", "Chq", "Cheque No", "Reference", "Tran Id", "UTR", "Chq/Ref No"]
        }
        self.date_pattern = re.compile(r'\d{2}[/-]\d{2}[/-]\d{2,4}')
        
    def get_password(self, pdf_path):
        """Prompt user for password."""
        print(f"\nLocked PDF detected: {os.path.basename(pdf_path)}")
        return getpass.getpass("Enter Password: ")

    def identify_headers(self, page_words):
        """
        Scan page words to find a row that looks like a header using Fuzzy Matching.
        Returns a dict mapping standard column names to their x-coordinates (x0, x1).
        """
        # Group words by line (approximate)
        words = sorted(page_words, key=lambda w: w['top'])
        lines = []
        if not words:
            return None, 0
            
        current_line = [words[0]]
        for w in words[1:]:
            if abs(w['top'] - current_line[-1]['top']) < 5:
                current_line.append(w)
            else:
                lines.append(current_line)
                current_line = [w]
        lines.append(current_line)

        # Scan lines for headers
        best_header_match = {}
        max_matches = 0
        header_top = 0
        
        for line in lines[:20]: # Only check top 20 lines
            matched_cols = {}
            
            # Create a simplified text representation of the line for context, though we process word by word
            # Actually, bank headers are often single words or short phrases.
            # We will test each word/phrase in the line against our synonyms.
            
            # Challenge: "Value Date" is two words. Splitting by word might break it.
            # Workaround: Check words, and also check combined adjacent words?
            # Simpler approach V1: Check each word. If match > 90, accept.
            
            for w in line:
                text = w['text']
                if len(text) < 3: # Skip small noise to avoid warnings and false positives
                    continue
                
                # Check against all synonym lists
                best_score = 0
                best_category = None
                
                for category, synonyms in self.header_synonyms.items():
                    # 1. Primary: Explicit Partial Match (Robust for concatenated words like "ClosingBalance")
                    # We check if any synonym is a substring of the text
                    if any(syn.lower() in text.lower() for syn in synonyms):
                         best_score = 100
                         best_category = category
                         break
                    
                    # 2. Secondary: Fuzzy Match (Robust for typos like "Dte" or "Balnce")
                    match, score = process.extractOne(text, synonyms, scorer=fuzz.partial_ratio)
                    if score > 85: 
                         if score > best_score:
                             best_score = score
                             best_category = category
                
                if best_category and best_score > 85:
                    if best_category not in matched_cols:
                         matched_cols[best_category] = {'x0': float(w['x0']), 'x1': float(w['x1']), 'top': float(w['top'])}

            if len(matched_cols) > max_matches:
                max_matches = len(matched_cols)
                best_header_match = matched_cols
                header_top = matched_cols[list(matched_cols.keys())[0]]['top']
        
        if max_matches >= 3: # require at least 3 recognizable signals
            # Construct column boundaries based on header positions
            # We sort columns by x0 to determine order
            sorted_cols = sorted(best_header_match.items(), key=lambda x: x[1]['x0'])
            
            boundaries = []
            for i in range(len(sorted_cols)):
                col_name = sorted_cols[i][0]
                start_x = sorted_cols[i][1]['x0']
                
                # End x is the start of the next column, or page width (assumed 1000 for now)
                if i < len(sorted_cols) - 1:
                    # The boundary is halfway between this header's start and next header's start?
                    # Or strictly at next header start?
                    # Using halfway point is safer for centering, but "start of next - offset" is safer for left-aligned.
                    # Given the issue with Date vs Narration, let's use a tighter bound if possible.
                    next_start = sorted_cols[i+1][1]['x0']
                    
                    # Heuristic: If detecting Date, cap its width if the gap is huge?
                    # No, let's just stick to "start of next column" as the hard wall for now.
                    end_x = next_start
                else:
                    end_x = 1000.0 # Far right
                
                boundaries.append({
                    'name': col_name,
                    'x0': start_x - 10, # Give a little margin to the left
                    'x1': end_x - 2 # Tighten the right margin so we don't bleed too much
                })
                
            return boundaries, header_top
            
        return None, 0

    def extract_data(self, pdf_path, known_password=None):
        out_data = []
        try:
            # Try opening first without password, then catch exception
            try:
                pdf = pdfplumber.open(pdf_path, password=known_password)
            except Exception as e:
                # If password failed or needed
                if "password" in str(e).lower() or "encrypted" in str(e).lower(): 
                   pwd = self.get_password(pdf_path)
                   pdf = pdfplumber.open(pdf_path, password=pwd)
                else:
                    raise e
            
            with pdf:
                print(f"Processing {pdf_path}...")
                column_layout = None
                header_y = 0
                
                # First pass: find header on first page
                if len(pdf.pages) > 0:
                    words = pdf.pages[0].extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
                    column_layout, header_y = self.identify_headers(words)
                
                if not column_layout:
                    print(f"Could not identify table headers in {pdf_path}. Skipping.")
                    return []

                print(f"Detected columns: {[c['name'] for c in column_layout]}")

                current_record = None

                # Extraction Pass
                for page in pdf.pages:
                    words = page.extract_words(keep_blank_chars=True, x_tolerance=2, y_tolerance=2)
                    words.sort(key=lambda w: w['top'])
                    
                    # Group into lines
                    lines = []
                    if words:
                        current_line = [words[0]]
                        for w in words[1:]:
                            if abs(w['top'] - current_line[-1]['top']) < 3:
                                current_line.append(w)
                            else:
                                lines.append(current_line)
                                current_line = [w]
                        lines.append(current_line)

                    for line in lines:
                        # Skip lines above header
                        if list(line)[0]['top'] <= header_y + 5:
                            continue
                        
                        # --- Noise Filtering ---
                        line_text = " ".join([w['text'].lower() for w in line])
                        ignore_phrases = [
                            "for any queries", "customer service", "page no", 
                            "system generated", "to avail our loan", "union bank", 
                            "statement of account", "branch", "missed call", "sms <uloan>",
                            "contents of this statement", "generated on", "requesting branch code"
                        ]
                        if any(phrase in line_text for phrase in ignore_phrases):
                            continue
                        # -----------------------

                        row_data = {col['name']: [] for col in column_layout}
                        
                        # Assign words to columns based on simple x-coordinates
                        for w in line:
                            w_mid = (w['x0'] + w['x1']) / 2
                            # Use X0 (left edge) preference? For left-aligned text, w['x0'] matters more.
                            for col in column_layout:
                                # Adjusted logic: if word starts before column ends.
                                if col['x0'] <= w_mid < col['x1']:
                                    row_data[col['name']].append(w['text'])
                                    break
                        
                        # Flatten list to string
                        flat_row = {
                            k: " ".join(v).strip() 
                            for k, v in row_data.items()
                        }

                        # --- Smart Post-Processing ---
                        
                        # 1. Handle "Date" column pollution
                        # If "Date" column contains text that isn't a date, it might be spillover remarks.
                        row_date_text = flat_row.get("Date", "")
                        real_date = ""
                        spillover_text = ""
                        
                        if row_date_text:
                            # Search for date pattern
                            match = self.date_pattern.search(row_date_text)
                            if match:
                                real_date = match.group(0)
                                # Everything else is spillover? 
                                # If the date is at the start, the rest is spillover.
                                if len(row_date_text) > len(real_date) + 2:
                                    # Very loose heuristic: if text is significantly longer than a date
                                    spillover_text = row_date_text.replace(real_date, "").strip()
                                flat_row["Date"] = real_date
                            else:
                                # No date found in the date column.
                                # This is likely a continuation line (Remarks spillover)
                                spillover_text = row_date_text
                                flat_row["Date"] = ""

                        # 2. Logic to decide if New Record or Continuation
                        is_new_record = bool(flat_row.get("Date"))
                        
                        if is_new_record:
                            # If we have a pending record, save it
                            if current_record:
                                out_data.append(current_record)
                            
                            # Start new record
                            current_record = flat_row
                            # If we found spillover in the date column, move it to remarks
                            if spillover_text and "Remarks" in current_record:
                                current_record["Remarks"] = spillover_text + " " + current_record["Remarks"]
                            elif spillover_text and "Remarks" not in current_record:
                                # Fallback if Remarks column wasn't detected (rare)
                                pass 
                        else:
                            # Continuation line
                            if current_record:
                                # Append content to valid columns
                                if spillover_text and "Remarks" in current_record:
                                    current_record["Remarks"] += " " + spillover_text
                                
                                # Append other columns (e.g. if Remarks wrapped to Remarks column, or Description wrapped)
                                for col, val in flat_row.items():
                                    if col != "Date" and val:
                                        if current_record.get(col):
                                            current_record[col] += " " + val
                                        else:
                                            current_record[col] = val
                            else:
                                # No current record (orphan line at start?), skip or create specific catch-all?
                                pass
                                
                # Append last record
                if current_record:
                    out_data.append(current_record)

        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")
            return []
            
        return out_data

if __name__ == "__main__":
    scraper = BankStatementScraper()
    
    # Check for CLI args for password or file
    target_pdf = None
    pwd = None
    
    # Simple CLI argument parsing
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg.endswith(".pdf"):
            target_pdf = arg
        if arg.startswith("--pass="):
            pwd = arg.split("=")[1]
            
    files_to_process = [target_pdf] if target_pdf else [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
    
    all_data = []
    
    for f in files_to_process:
        if not os.path.exists(f): 
            print(f"File not found: {f}")
            continue
            
        print(f"--- Scanning {f} ---")
        data = scraper.extract_data(f, known_password=pwd)
        if data:
            all_data.extend(data)
            # Save individual JSON
            base_name = os.path.splitext(f)[0]
            with open(f"{base_name}.json", "w") as jf:
                json.dump(data, jf, indent=2)
            print(f"Saved {base_name}.json")
            
    # Save combined
    if len(all_data) > 0:
        df = pd.DataFrame(all_data)
        df.to_csv("combined_output.csv", index=False)
        print("\nSaved combined_output.csv")

