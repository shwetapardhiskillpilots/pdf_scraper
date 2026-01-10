import sys
import os
import re
import json
import getpass
import argparse

import pdfplumber
import pandas as pd
from thefuzz import process, fuzz

class BaseBankScraper:
    """
    Base scraper that works for most bank statements.
    Each bank can extend this and override specific methods for their quirks.
    """
    
    def __init__(self):
        # These are the column types we're looking for in any statement
        self.target_headers = ["Date", "Remarks", "Withdrawals", "Deposits", "Balance", "RefNo"]
        
        # Different banks call the same columns by different names, so we map them
        self.header_synonyms = {
            "Date": ["Date", "Txn Date", "Transaction Date", "Value Date", "Date of Txn"],
            "Remarks": ["Remarks", "Description", "Narration", "Particulars", "Transaction Details", "Details"],
            "Withdrawals": ["Withdrawals", "Debit", "Dr", "Withdrawal Amt", "Debit Amount"],
            "Deposits": ["Deposits", "Credit", "Cr", "Deposit Amt", "Credit Amount"],
            "Balance": ["Balance", "Bal", "Closing Balance", "Net Balance"],
            "RefNo": ["Ref No", "Chq", "Cheque No", "Reference", "Tran Id", "UTR", "Chq/Ref No"]
        }
        
        # Words that indicate it's just footer/header junk, not actual data
        self.noise_keywords = ["page no"]
        
        # Regex patterns to find dates and times in the text
        self.date_pattern = re.compile(r'\d{2}[/-]\d{2}[/-]\d{2,4}')
        self.time_pattern = re.compile(r'\d{2}:\d{2}(?::\d{2})?')

    def get_password(self, pdf_path):
        """Ask user for password if PDF is locked"""
        print(f"\nLocked PDF detected: {os.path.basename(pdf_path)}")
        return getpass.getpass("Enter Password: ")

    def is_line_noise(self, line_text):
        """Check if this line is just footer/header garbage. Banks can override this."""
        return any(nk.lower() in line_text.lower() for nk in self.noise_keywords)

    def is_transaction_start(self, line, line_text):
        """
        Figure out if this line starts a new transaction.
        We look for a date at the very beginning of the line (far left side).
        """
        first_word = line[0]['text'].strip()
        if self.date_pattern.match(first_word) and line[0]['x0'] < 100:
            return True
        return False

    def identify_headers(self, page_words, page_width=1000):
        """
        Find the header row and figure out where each column is.
        This is the trickiest part - we need to group words that belong together
        and figure out which column category they represent.
        """
        words = sorted(page_words, key=lambda w: w['top'])
        lines = []
        if not words: return None, 0
            
        # Group words into lines based on their vertical position
        current_line = [words[0]]
        for w in words[1:]:
            if abs(w['top'] - current_line[-1]['top']) < 3:  # Same line if within 3px
                current_line.append(w)
            else:
                current_line.sort(key=lambda x: x['x0'])
                lines.append(current_line)
                current_line = [w]
        current_line.sort(key=lambda x: x['x0'])
        lines.append(current_line)

        best_header_match = []
        max_matches = 0
        header_top = 0
        
        # Helper to figure out what category a piece of text belongs to
        def get_cat(txt):
            for category, synonyms in self.header_synonyms.items():
                if any(syn.lower() in txt.lower() for syn in synonyms): 
                    return category
                # Use fuzzy matching for slight variations
                if len(txt) > 3:
                    match, score = process.extractOne(txt, synonyms, scorer=fuzz.partial_ratio)
                    if score > 90: 
                        return category
            return None

        # Scan the first 30 lines looking for the header row
        for idx, line in enumerate(lines[:30]): 
            # Skip lines that are obviously noise
            line_text = " ".join([w['text'].lower() for w in line])
            if self.is_line_noise(line_text):
                continue
                
            matched_count = 0
            temp_headers = []
            if not line: continue
            
            # Group words that are close together horizontally into single header names
            # e.g., "Withdrawal" and "Amt." should become "Withdrawal Amt."
            current_group = [line[0]]
            grouped_tokens = []
            for w in line[1:]:
                gap = w['x0'] - current_group[-1]['x1']
                
                curr_txt = " ".join([cg['text'] for cg in current_group])
                next_txt = w['text']
                
                curr_cat = get_cat(curr_txt)
                next_cat = get_cat(next_txt)
                
                # Don't merge if they're clearly different columns
                is_different_cat = curr_cat and next_cat and curr_cat != next_cat
                
                # Usually words within 9px are part of the same header
                # But for "Instr. ID" type headers, allow up to 40px
                allowed_gap = 9
                if curr_cat and next_cat and curr_cat == next_cat:
                    if "instr" in curr_txt.lower() or "id" in next_txt.lower():
                        allowed_gap = 40
                
                if gap < allowed_gap and not is_different_cat:
                    current_group.append(w)
                else:
                    grouped_tokens.append(current_group)
                    current_group = [w]
            grouped_tokens.append(current_group)
            
            # Now check each grouped token to see if it's a valid header
            for group in grouped_tokens:
                text = " ".join([w['text'] for w in group]).strip()
                # Clean up any weird characters
                text = "".join(c for c in text if 31 < ord(c) < 127).strip()
                text = re.sub(r'\s+', ' ', text)
                if len(text) < 2: continue
                best_cat = get_cat(text)
                if best_cat: matched_count += 1
                temp_headers.append({
                    'original_name': text, 'category': best_cat,
                    'x0': float(group[0]['x0']), 'x1': float(group[-1]['x1']),
                    'top': float(group[0]['top'])
                })

            # Keep track of the line with the most header matches
            if matched_count > max_matches:
                max_matches = matched_count
                best_header_match = temp_headers
                header_top = min(h['top'] for h in temp_headers)
        
        # If we found at least 3 column headers, we're good
        if max_matches >= 3:
            sorted_headers = sorted(best_header_match, key=lambda x: x['x0'])
            column_layout = []
            
            # Define column boundaries using midpoints between headers
            # This gives us some wiggle room for data that's slightly off-center
            for i in range(len(sorted_headers)):
                curr_h = sorted_headers[i]
                left = 0 if i == 0 else (sorted_headers[i-1]['x1'] + curr_h['x0']) / 2
                right = page_width if i == len(sorted_headers)-1 else (curr_h['x1'] + sorted_headers[i+1]['x0']) / 2
                column_layout.append({
                    'name': curr_h['original_name'], 
                    'category': curr_h['category'], 
                    'x0': left, 
                    'x1': right
                })
            return column_layout, header_top
        return None, 0

    def extract_data(self, pdf_path, known_password=None):
        out_data = []
        try:
            pdf = None
            # Try to open the PDF, handling password-protected files
            try:
                pdf = pdfplumber.open(pdf_path)
            except Exception as e:
                if known_password:
                    try: 
                        pdf = pdfplumber.open(pdf_path, password=known_password)
                    except: 
                        pass
                if not pdf:
                    if "password" in str(e).lower() or "encrypted" in str(e).lower() or not str(e):
                       pdf = pdfplumber.open(pdf_path, password=self.get_password(pdf_path))
                    else: 
                        raise e
            
            with pdf:
                # First, figure out where the columns are by looking at the first page
                column_layout, header_y = None, 0
                if len(pdf.pages) > 0:
                    column_layout, header_y = self.identify_headers(
                        pdf.pages[0].extract_words(), 
                        float(pdf.pages[0].width)
                    )
                
                if not column_layout:
                    print(f"Couldn't find table headers in {pdf_path}. Skipping.")
                    return []

                # Find which columns are the date and remarks (we need these for special handling)
                date_col = next((c['name'] for c in column_layout if c['category'] == 'Date'), None)
                remarks_col = next((c['name'] for c in column_layout if c['category'] == 'Remarks'), None)
                current_record = None

                # Now process each page
                for page in pdf.pages:
                    words = page.extract_words()
                    words.sort(key=lambda w: w['top'])
                    
                    # Group words into lines again
                    lines = []
                    if words:
                        cl = [words[0]]
                        for w in words[1:]:
                            if abs(w['top'] - cl[-1]['top']) < 3: 
                                cl.append(w)
                            else:
                                cl.sort(key=lambda x: x['x0'])
                                lines.append(cl)
                                cl = [w]
                        cl.sort(key=lambda x: x['x0'])
                        lines.append(cl)

                    # Process each line
                    for line in lines:
                        # Skip the header row
                        if line[0]['top'] <= header_y + 5: 
                            continue
                        
                        text = " ".join([w['text'] for w in line])
                        
                        # Skip footer/header junk, unless it's actually a transaction
                        if self.is_line_noise(text) and not self.is_transaction_start(line, text):
                            continue
                        
                        # Track vertical position to detect multi-line transactions
                        top = line[0]['top']
                        gap = (top - current_record.get('_lt', 0)) if current_record else 0
                        
                        # Assign each word to its column based on horizontal position
                        row_raw = {c['name']: [] for c in column_layout}
                        for w in line:
                            best_col = None
                            max_ov = 0
                            for c in column_layout:
                                # Calculate overlap between word and column
                                ov = min(w['x1'], c['x1']) - max(w['x0'], c['x0'])
                                if ov > max_ov: 
                                    max_ov, best_col = ov, c['name']
                            if best_col: 
                                row_raw[best_col].append(w['text'])
                        
                        if any(row_raw.values()):
                            flat = {k: " ".join(v).strip() for k, v in row_raw.items()}
                            rd_txt = flat.get(date_col, "").strip() if date_col else ""
                            dm = self.date_pattern.search(rd_txt)
                            tm = self.time_pattern.search(rd_txt)
                            
                            # Check if this line is just a time (continuation of previous transaction)
                            is_iso_time = bool(tm and not dm)
                            r_date, f_time, spill = "", "", ""
                            if dm: r_date = dm.group(0)
                            if tm: f_time = tm.group(0)
                            if dm: 
                                # If there's extra text after the date, it probably belongs in remarks
                                spill = rd_txt.replace(r_date, "").replace(f_time, "").strip()
                                if len(spill) < 2: spill = ""

                            # Decide if this is a new transaction or continuation of the previous one
                            if self.is_transaction_start(line, text):
                                # Save the previous transaction if there was one
                                if current_record:
                                    current_record.pop('_lt', None)
                                    out_data.append(current_record)
                                # Start a new transaction
                                current_record = flat
                                current_record['_lt'] = top
                                current_record[date_col] = f"{r_date} {f_time}".strip()
                                if spill and remarks_col:
                                    current_record[remarks_col] = (spill + " " + current_record.get(remarks_col, "")).strip()
                            else:
                                # This is a continuation line - merge it into the current transaction
                                # But only if it's close enough vertically (< 20px gap)
                                if current_record and gap < 20:
                                    current_record['_lt'] = top
                                    
                                    # If it's just a time, add it to the date
                                    if is_iso_time and date_col:
                                        cv = current_record.get(date_col, "")
                                        if rd_txt not in cv: 
                                            current_record[date_col] = f"{cv} {f_time}".strip()
                                    
                                    # Merge any other text into remarks
                                    if rd_txt and not is_iso_time: 
                                        spill = rd_txt
                                    if spill and remarks_col:
                                        current_record[remarks_col] = (current_record.get(remarks_col, "") + " " + spill).strip()
                                    
                                    # Merge data from other columns too
                                    for cn, val in flat.items():
                                        if cn != date_col and val:
                                            # Don't duplicate the spillover text
                                            if cn == remarks_col and val.strip() == spill.strip(): 
                                                continue
                                            cv = current_record.get(cn, "")
                                            if val not in cv: 
                                                current_record[cn] = (cv + " " + val).strip()
                    
                    # IMPORTANT: Don't reset current_record here!
                    # Transactions can span across pages, so we keep the record alive
                
                # After processing all pages, save the last transaction
                if current_record:
                    current_record.pop('_lt', None)
                    out_data.append(current_record)

        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")
            return []
        return out_data

class UnionBankScraper(BaseBankScraper):
    """Union Bank has a lot of promotional junk in their PDFs, so we filter it out."""
    def __init__(self):
        super().__init__()
        self.noise_keywords = [
            "page no", "union bank", "statement of account", "generated on",
            "avail our loan", "missed call", "sms <uloan>", "discrepancy",
            "notify the bank", "computer generated", "no signature",
            "visit our website", "for any queries", "customer service"
        ]

    def is_line_noise(self, line_text):
        lt = line_text.lower()
        # Check for any of our noise keywords
        if any(nk in lt for nk in self.noise_keywords): 
            return True
        # Also check for lines with multiple promotional words (likely an ad)
        promo_words = ["avail", "loan", "products", "missed", "call", "sms", "uloan"]
        if sum(1 for pw in promo_words if pw in lt) >= 2: 
            return True
        return False

class HDFCBankScraper(BaseBankScraper):
    """HDFC-specific scraper. Their statements are pretty clean, just a few noise patterns."""
    def __init__(self):
        super().__init__()
        self.noise_keywords = [
            "page no", "hdfc bank", "statement of account", "generated on",
            "customer care", "registered office"
        ]

    def is_line_noise(self, line_text):
        lt = line_text.lower()
        if any(nk in lt for nk in self.noise_keywords): 
            return True
        return False

class ScraperFactory:
    """Simple factory to get the right scraper based on bank name."""
    @staticmethod
    def get_scraper(bank_name):
        bank_map = {
            "union_bank": UnionBankScraper,
            "hdfc": HDFCBankScraper,
            "generic": BaseBankScraper
        }
        scraper_cls = bank_map.get(bank_name.lower(), BaseBankScraper)
        return scraper_cls()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Bank PDF Scraper")
    parser.add_argument("pdf", nargs="?", help="PDF file to scrape")
    parser.add_argument("--bank", default="generic", choices=["union_bank", "hdfc", "generic"], help="Bank type")
    parser.add_argument("--pass", dest="password", help="PDF password")
    args = parser.parse_args()

    factory = ScraperFactory()
    scraper = factory.get_scraper(args.bank)
    
    files = [args.pdf] if args.pdf else [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
    all_results = []
    
    for f in files:
        if not os.path.exists(f): continue
        print(f"--- Using {args.bank} scraper for {f} ---")
        data = scraper.extract_data(f, known_password=args.password)
        if data:
            all_results.extend(data)
            base = os.path.splitext(f)[0]
            with open(f"{base}.json", "w") as jf:
                json.dump(data, jf, indent=2)
            print(f"Saved {base}.json")
            
    if all_results:
        pd.DataFrame(all_results).to_csv("combined_output.csv", index=False)
        print("\nSaved combined_output.csv")
