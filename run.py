import uvicorn
import os
import sys

# Ensure the root directory is in sys.path so app module is discoverable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    # Start the FastAPI app using the app.main:app import string
    # This ensures that relative imports within the app package work correctly.
    uvicorn.run("app.main:app", host="0.0.0.0", port=6543, reload=True)
