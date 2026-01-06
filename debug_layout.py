import pdfplumber

pdf_file = "UB CC 1.pdf"

with pdfplumber.open(pdf_file) as pdf:
    page = pdf.pages[0]
    words = page.extract_words()
    
    print("--- FIRST 50 WORDS WITH COORDINATES ---")
    for word in words[:50]:
        print(f"Text: {word['text']:<20} | x0: {word['x0']:.2f} | x1: {word['x1']:.2f} | top: {word['top']:.2f}")

    print("\n--- FINDING HEADER POSITIONS ---")
    # Search for specific header keywords to guess column tops/lefts
    headers = ["Date", "Remarks", "Tran", "UTR", "Instr", "Withdrawals", "Deposits", "Balance"]
    for word in words:
        if any(h in word['text'] for h in headers):
            print(f"HEADER match: {word['text']:<20} | x0: {word['x0']:.2f} | x1: {word['x1']:.2f} | top: {word['top']:.2f}")
