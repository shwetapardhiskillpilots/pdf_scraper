# Use an official lightweight Python image.
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (needed for some PDF processing and library builds)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY app/ ./app/
COPY run.py .

# Create directories for physical storage (uploads and outputs)
RUN mkdir -p uploads outputs

# Expose the API port
EXPOSE 6543

# Run the application
CMD ["python", "run.py"]
