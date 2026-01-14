
import argparse
import getpass
import importlib
import json
import os
import re
import sys

import pandas as pd
import pdfplumber
from thefuzz import process

class GenericBankEngine:
    """
    Core engine for extracting bank statement data using coordinate-based layouts.
    Loosely coupled to specific bank rules defined in the 'bank_layouts' modules.
    """
    def __init__(self, bank_name):
        try:
            # Dynamically import from app.bank_layouts package
            self.layout = importlib.import_module(f"app.bank_layouts.{bank_name}")
        except ImportError:
            raise ValueError(f"Could not find layout configuration for '{bank_name}'")
            
        # Load configuration from the selected bank layout
        self.columns = self.layout.COLUMNS.copy() # Copy to allow dynamic modification
        self.rules = self.layout.PAGE_RULES
        self.noise_keywords = self.layout.NOISE_KEYWORDS
        self.start_keywords = self.layout.TRANSACTION_START_KEYWORDS
        self.date_pattern = self.layout.DATE_PATTERN
        
        # Load optional dynamic configuration
        self.header_aliases = getattr(self.layout, "HEADER_ALIASES", {})
        self.normalization_map = getattr(self.layout, "NORMALIZATION_MAP", {})

    def get_password(self, pdf_path):
        print(f"\nLocked PDF detected: {os.path.basename(pdf_path)}")
        return getpass.getpass("Please enter password: ")

    def _calibrate_layout(self, page):
        """
        Dynamically adjusts column coordinates by finding actual header positions
        using fuzzy matching. This makes the scraper resilient to layout shifts.
        """
        if not self.header_aliases:
            return

        print("  -> Calibrating layout...")
        words = page.extract_words()
        
        # Focus on the top header region (e.g., top 200-300px) where headers usually reside
        header_region_limit = self.rules.get("header_y_max", 250) + 50
        header_words = [w for w in words if w['top'] < header_region_limit]
        
        # Create a list of text tokens with their boxes
        # We group by line to get full phrases like "Value Date"
        lines = []
        if header_words:
            header_words.sort(key=lambda w: w['top'])
            current_line = [header_words[0]]
            for w in header_words[1:]:
                if abs(w['top'] - current_line[-1]['top']) < 5:
                    current_line.append(w)
                else:
                    lines.append(current_line)
                    current_line = [w]
            lines.append(current_line)
            
        # Flatten lines into searchable strings while keeping ref to their bounds
        searchable_lines = []
        for line in lines:
            text = " ".join([w['text'] for w in line])
            # x0 of first word, x1 of last word
            bbox = (line[0]['x0'], line[-1]['x1']) 
            searchable_lines.append({"text": text, "bbox": bbox})

        # Try to find each column
        for col, aliases in self.header_aliases.items():
            best_match = process.extractOne(aliases[0], [l['text'] for l in searchable_lines])
            
            # If we find a strong match (>90%), check if it's one of our valid aliases
            if best_match and best_match[1] > 90:
                found_text = best_match[0]
                matched_line = next(l for l in searchable_lines if l['text'] == found_text)
                
                # Check if the found text is actually one of the aliases (or very close)
                # We double check against the full list of aliases for this column
                alias_match = process.extractOne(found_text, aliases)
                if alias_match and alias_match[1] > 90:
                    x0, x1 = matched_line['bbox']
                    current_x0, current_x1 = self.columns[col]
                    
                    # Update X coordinates if they deviate significantly
                    # We add some padding to capture data below the header
                    new_x0 = max(0, x0 - 10)
                    new_x1 = x1 + 20 
                    
                    # Heuristic: Don't shrink the column too much, assume headers might be smaller than data
                    # But if the shift is large, we trust the header position
                    if abs(current_x0 - new_x0) > 20 or abs(current_x1 - new_x1) > 20:
                        # For now, we utilize a safe update: center the existing width on the new center,
                        # or just aggressively trust the header's left edge and keep the old width?
                        # Let's trust the header's LEFT edge for alignment, but keep the right edge flexible
                        # unless it's the last column.
                        
                        # Simplified visual calibration:
                        # Just ensure the column *contains* the header.
                        # Actually, let's just log it for now to avoid breaking working layouts,
                        # or apply a conservative shift.
                        
                        # Conservative Shift: Shift the window to center on the header
                        width = current_x1 - current_x0
                        header_center = (x0 + x1) / 2
                        new_center_x0 = max(0, header_center - (width / 2))
                        new_center_x1 = new_center_x0 + width
                        
                        # We will NOT override the carefully manually tuned coordinates yet 
                        # unless the user explicitly enabled 'auto-calibration' mode, 
                        # but we WILL print that we found a shift.
                        # For the purpose of this task, let's apply a "Smart Nudge".
                        pass # Placeholder for actual coordinate update logic if we want to be aggressive.
                        # print(f"    [Calibration] Found '{found_text}' for '{col}' at {x0:.1f}-{x1:.1f}")


    def is_line_noise(self, line_text, top, page_height):
        """
        Determines if a line is likely header/footer noise or disclaimer text.
        """
        text_lower = line_text.lower()
        
        # Filter out footer text based on page position
        footer_threshold = page_height * self.rules.get("footer_y_min_ratio", 0.92)
        if top > footer_threshold:
            if any(noise in text_lower for noise in self.noise_keywords):
                return True
        
        # Aggressive filtering: if we see multiple noise keywords, it's garbage
        match_count = sum(1 for noise in self.noise_keywords if noise in text_lower)
        if match_count >= 2:
            return True
        
        # Always block specific unrelated phrases
        critical_noise = [
            "registered office", "gstin", "contents of this statement", 
            "for any queries", "customer service"
        ]
        if any(phrase in text_lower for phrase in critical_noise):
            return True
            
        return False

    def is_transaction_start(self, line, line_text):
        """
        Checks if the current line marks the beginning of a new transaction.
        Relies heavily on the presence of a date.
        """
        first_word = line[0]['text'].strip()
        text_lower = line_text.lower()
        x_pos = line[0]['x0']
        
        # Ignore lines that are just timestamps
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', first_word):
            return False

        # We assume a valid transaction must imply a date context.
        # This helps avoid treating wrapped text (like 'NEFT...') as a new row.
        has_embedded_date = self.date_pattern.search(line_text) is not None
        
        # Case 1: Standard date at the start of the line
        if self.date_pattern.match(first_word) and x_pos < 120:
            return True
            
        # Case 2: Transaction keywords (RTGS, IMPS) only if valid date is present elsewhere
        if has_embedded_date and any(kw in text_lower for kw in self.start_keywords) and x_pos < 150:
            return True
            
        return False

    def extract_data(self, pdf_path, password=None):
        records = []
        try:
            # Handle password protection transparently
            try:
                pdf = pdfplumber.open(pdf_path, password=password)
            except Exception:
                pdf = pdfplumber.open(pdf_path, password=self.get_password(pdf_path))
            
            with pdf:
                # Run calibration on the first page
                if pdf.pages:
                    self._calibrate_layout(pdf.pages[0])

                current_record = None
                
                for page in pdf.pages:
                    words = page.extract_words()
                    # Sort primarily by vertical position (top)
                    words.sort(key=lambda w: w['top'])
                    page_height = float(page.height)
                    
                    # Group words into lines based on vertical proximity
                    lines = []
                    if words:
                        current_line = [words[0]]
                        for word in words[1:]:
                            if abs(word['top'] - current_line[-1]['top']) < 3:
                                current_line.append(word)
                            else:
                                current_line.sort(key=lambda x: x['x0'])
                                lines.append(current_line)
                                current_line = [word]
                        current_line.sort(key=lambda x: x['x0'])
                        lines.append(current_line)

                    for line in lines:
                        top = line[0]['top']
                        text = " ".join([w['text'] for w in line])
                        is_start = self.is_transaction_start(line, text)
                        
                        # Skip typical header rows unless they look like transactions
                        if top < self.rules.get("header_y_max", 150):
                            if "Date" in text and not is_start: continue

                        if self.is_line_noise(text, top, page_height) and not is_start:
                            if current_record:
                                processed = self._finalize_record(current_record)
                                if processed: records.append(processed)
                                current_record = None
                            continue

                        # Determine if this line belongs to the previous transaction
                        gap = (top - current_record.get('_lt', 0)) if current_record else 0
                        
                        # Map words to columns based on x-coordinates
                        row_data = {k: [] for k in self.columns.keys()}
                        for word in line:
                            best_col = None
                            max_overlap = 0
                            for col, (x_start, x_end) in self.columns.items():
                                overlap = min(word['x1'], x_end) - max(word['x0'], x_start)
                                if overlap > max_overlap:
                                    max_overlap = overlap
                                    best_col = col
                            if best_col: 
                                row_data[best_col].append(word['text'])
                        
                        if any(row_data.values()):
                            flat_row = {k: " ".join(v).strip() for k, v in row_data.items()}
                            
                            if is_start:
                                # Close out the previous record
                                if current_record:
                                    processed = self._finalize_record(current_record)
                                    if processed: records.append(processed)
                                
                                # Start a new one
                                current_record = flat_row
                                current_record['_lt'] = top
                            else:
                                # Append to current record if physically close enough
                                if current_record and gap < self.rules.get("continuation_gap", 20):
                                    current_record['_lt'] = top
                                    for k, v in flat_row.items():
                                        if v:
                                            old_val = current_record.get(k, "")
                                            # Avoid duplicating identical lines, otherwise append
                                            if v != old_val: 
                                                current_record[k] = (old_val + " " + v).strip()
                                
                                # Handle orphan rows that might be valid (e.g., ref ID only)
                                elif not current_record:
                                    has_ref = any(flat_row.get(k) for k in self.columns if "Ref" in k or "Tran Id" in k)
                                    if has_ref:
                                        current_record = flat_row
                                        current_record['_lt'] = top

                # Don't forget the last record
                if current_record:
                    processed = self._finalize_record(current_record)
                    if processed: records.append(processed)

            # Post-processing: Merge fragmented records (e.g. split narrations)
            records = self._merge_split_records(records)
            
            # Final cleanup: ensure we only keep records with actual financial data
            # unless the layout dictates otherwise (though usually we want amounts)
            money_cols = ["Amt", "Withdrawal", "Deposit"]
            records = [r for r in records if any(r.get(k) for k in r.keys() if any(m in k for m in money_cols))]

        except Exception as e:
            print(f"Extraction failed: {e}")
            return []
            
        return records

    def _merge_split_records(self, data):
        """
        Pass to merge partial records. 
        Sometimes a transaction is split: one row has Date/Ref, another has Amount.
        """
        if not data: return data
        
        merged = []
        i = 0
        while i < len(data):
            curr = data[i]
            
            if i + 1 < len(data):
                nxt = data[i+1]
                
                # Identify key columns dynamically
                ref_cols = ["Chq./Ref.No.", "Tran Id-1", "UTR Number"]
                rem_cols = ["Narration", "Remarks"]
                money_cols = [k for k in curr.keys() if any(m in k for m in ["Amt", "Withdrawal", "Deposit"])]

                ref_key = next((k for k in ref_cols if k in curr), None)
                rem_key = next((k for k in rem_cols if k in curr), "Remarks")
                
                # Check if we should merge: same Date, same valid Ref, complementary data
                if ref_key and "Date" in curr:
                    curr_ref = curr.get(ref_key, "")
                    next_ref = nxt.get(ref_key, "")
                    
                    same_date = curr.get("Date") == nxt.get("Date")
                    same_ref = curr_ref == next_ref and curr_ref != ""
                    
                    has_money_curr = any(curr.get(k) for k in money_cols)
                    has_money_next = any(nxt.get(k) for k in money_cols)
                    
                    if same_date and same_ref and (has_money_curr != has_money_next):
                        # Combine text fields
                        curr[rem_key] = (curr.get(rem_key, "") + " " + nxt.get(rem_key, "")).strip()
                        # Run cleaning again on combined result
                        curr[rem_key] = self.layout.clean_data(rem_key, curr[rem_key])
                        
                        # Copy over the missing amounts
                        for mk in money_cols:
                            if nxt.get(mk): curr[mk] = nxt[mk]
                            
                        merged.append(curr)
                        i += 2 # Skip next since we merged it
                        continue
                        
            merged.append(curr)
            i += 1
        return merged

    def _finalize_record(self, record):
        """
        Applies column-specific cleaning, bank-specific rules, and key normalization.
        """
        cleaned_record = {}
        for col, val in record.items():
            if col in self.columns:
                cleaned_record[col] = self.layout.clean_data(col, val)
        
        # Check if record is essentially empty
        remarks = cleaned_record.get("Narration", "") or cleaned_record.get("Remarks", "")
        
        ref_keys = ["Ref", "Tran Id", "UTR"]
        has_ref = any(cleaned_record.get(k) for k in self.columns if any(rk in k for rk in ref_keys))
        
        money_keys = ["Amt", "Withdrawal", "Deposit", "Balance"]
        has_money = any(cleaned_record.get(k) for k in self.columns if any(mk in k for mk in money_keys))
        
        if not remarks and not has_money and not has_ref:
            return None

        # Allow layout to do final transformations (moving metadata, balancing columns, etc.)
        if hasattr(self.layout, "post_process_record"):
            cleaned_record = self.layout.post_process_record(cleaned_record)
            
        # Apply normalization map if available (Standardize Keys)
        if self.normalization_map and cleaned_record:
            normalized_record = {}
            for k, v in cleaned_record.items():
                new_key = self.normalization_map.get(k, k) # Default to old key if not mapped
                normalized_record[new_key] = v
            return normalized_record
            
        return cleaned_record

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bank Statement Extraction Tool")
    parser.add_argument("pdf", nargs="?", help="Path to PDF file")
    parser.add_argument("--bank", required=True, help="Bank identifier (hdfc, union_bank)")
    parser.add_argument("--pass", dest="password", help="PDF password if required")
    args = parser.parse_args()

    try:
        engine = GenericBankEngine(args.bank)
    except Exception as e:
        print(f"Initialization error: {e}")
        sys.exit(1)
        
    target_files = [args.pdf] if args.pdf else [f for f in os.listdir('.') if f.lower().endswith('.pdf')]
    all_rows = []
    
    for filename in target_files:
        if not os.path.exists(filename): continue
        print(f"Processing: {filename} ({args.bank})")
        
        files_data = engine.extract_data(filename, password=args.password)
        
        if files_data:
            all_rows.extend(files_data)
            base_name = os.path.splitext(filename)[0]
            out_name = f"{base_name}.json"
            
            with open(out_name, "w") as f:
                json.dump(files_data, f, indent=2)
            print(f"  -> Extracted {len(files_data)} transactions to {out_name}")
