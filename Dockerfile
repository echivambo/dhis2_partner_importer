FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WORKDIR=/app

WORKDIR ${WORKDIR}

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port: 8000 for the FastAPI web server
EXPOSE 8000

# Command to start the FastAPI web application
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
