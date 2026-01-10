import gradio as gr
import os
import json
import pandas as pd
from scraper import ScraperFactory

def process_statement(pdf_file, bank_name, password):
    """Main function that handles the PDF upload and extraction"""
    if pdf_file is None:
        return "Please upload a PDF file.", "", None, None
    
    pdf_path = pdf_file.name
    factory = ScraperFactory()
    
    # Map the friendly dropdown names to our internal scraper keys
    bank_map = {
        "Union Bank": "union_bank",
        "HDFC": "hdfc",
        "Generic/Other": "generic"
    }
    
    internal_bank = bank_map.get(bank_name, "generic")
    scraper = factory.get_scraper(internal_bank)
    
    try:
        data = scraper.extract_data(pdf_path, known_password=password if password else None)
        
        if not data:
            return f"No transactions found using the {bank_name} scraper. Check your selection or password.", "", None, None
        
        # Format the JSON nicely for the preview
        json_preview = json.dumps(data, indent=2)
        
        # Make sure we have a place to save files
        os.makedirs("outputs", exist_ok=True)
        
        # Save both JSON and Excel versions
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        json_output = os.path.join("outputs", f"{base_name}_output.json")
        xlsx_output = os.path.join("outputs", f"{base_name}_output.xlsx")
        
        with open(json_output, "w") as f:
            json.dump(data, f, indent=2)
            
        df = pd.DataFrame(data)
        df.to_excel(xlsx_output, index=False)
        
        summary = f"✅ Successfully extracted {len(data)} transactions!"
        return summary, json_preview, json_output, xlsx_output
        
    except Exception as e:
        return f"❌ Error: {str(e)}", "", None, None

# Build the Gradio interface
with gr.Blocks(title="Bank Statement Scraper") as demo:
    gr.Markdown("# 🏦 Bank Statement PDF Scraper")
    gr.Markdown("Extract transactions from Union Bank (CC) and HDFC statements with high accuracy.")
    
    with gr.Row():
        # Left column - inputs
        with gr.Column():
            file_input = gr.File(label="Upload PDF Statement", file_types=[".pdf"])
            bank_dropdown = gr.Dropdown(
                choices=["Union Bank", "HDFC", "Generic/Other"], 
                value="Union Bank", 
                label="Select Bank Format"
            )
            password_input = gr.Textbox(
                label="PDF Password (if any)", 
                type="password", 
                placeholder="Leave blank if not encrypted"
            )
            process_btn = gr.Button("Extract Transactions", variant="primary")
            
        # Middle column - preview
        with gr.Column():
            status_output = gr.Textbox(label="Status", lines=2)
            json_preview = gr.Textbox(
                label="📄 Extracted Data (JSON Preview)", 
                lines=15, 
                max_lines=20,
                placeholder="Extracted transaction data will appear here..."
            )
            
        # Right column - downloads
        with gr.Column():
            json_file = gr.File(label="💾 Download JSON Output")
            excel_file = gr.File(label="📊 Download Excel (XLSX) Output")
            
    # Wire up the button to the processing function
    process_btn.click(
        fn=process_statement,
        inputs=[file_input, bank_dropdown, password_input],
        outputs=[status_output, json_preview, json_file, excel_file]
    )
    
    gr.Markdown("---")
    gr.Markdown("### Instructions")
    gr.Markdown("""
    1. **Upload** your bank statement PDF.
    2. **Select** the correct bank from the dropdown. 
    3. **Enter password** if the file is locked (like HDFC statements).
    4. **Download** your clean transaction data.
    """)

if __name__ == "__main__":
    demo.launch(share=False)
