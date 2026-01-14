import os
import shutil
import uuid
import json
import logging
import asyncio
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator

# Adjusted import for new structure
from app.services.scraper import GenericBankEngine

# --- Configuration & Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Thread pool for blocking PDF operations
executor = ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="Bank Scraper API (Production)")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In real prod, specify domain e.g., ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---
class BankResponse(BaseModel):
    key: str
    name: str

class ExtractionResponse(BaseModel):
    status: str
    job_id: str
    filename: str
    count: int
    transactions: List[dict]

# --- Helper Functions ---
def _run_extraction(bank_key: str, file_path: str, password: Optional[str]) -> List[dict]:
    """Blocking function to be run in thread pool"""
    logger.info(f"Starting extraction for {file_path} using {bank_key}")
    try:
        engine = GenericBankEngine(bank_key)
        data = engine.extract_data(file_path, password=password)
        logger.info(f"Extraction complete. Found {len(data)} records.")
        return data
    except Exception as e:
        logger.error(f"Extraction failed: {str(e)}")
        raise e

# --- Endpoints ---

@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Bank Scraper API is running (Production Mode)",
        "docs": "/docs",
        "endpoints": ["/extract", "/banks"]
    }

@app.get("/banks", response_model=dict, tags=["Metadata"])
async def list_banks():
    """Returns supported bank keys dynamically."""
    layouts_dir = os.path.join("app", "bank_layouts")
    banks = []
    
    if os.path.exists(layouts_dir):
        for filename in os.listdir(layouts_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                bank_key = filename[:-3]
                friendly_name = bank_key.replace("_", " ").title()
                banks.append({"key": bank_key, "name": friendly_name})
    
    return {"banks": banks}

@app.post("/extract", response_model=ExtractionResponse, tags=["Core"])
async def extract_data(
    file: UploadFile = File(...),
    bank_key: str = Form(...),
    password: Optional[str] = Form(None)
):
    """
    Unified Endpoint: Upload + Process + Result (Async).
    """
    # 1. Validation
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # 2. Staging
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{job_id}.pdf")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 3. Async Execution (Offload blocking CPU work)
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            executor, 
            _run_extraction, 
            bank_key, 
            file_path, 
            password
        )
        
        # 4. Persistence
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}.json")
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
            
        return {
            "status": "success",
            "job_id": job_id,
            "filename": file.filename,
            "count": len(data),
            "transactions": data
        }
        
    except ValueError as ve:
        logger.warning(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.critical(f"System error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    # finally:
    #     # Cleanup logic could go here
    #     pass

if __name__ == "__main__":
    import uvicorn
    # Use 0.0.0.0 for container/external access
    uvicorn.run(app, host="0.0.0.0", port=8002)
