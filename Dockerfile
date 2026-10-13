FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout for docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY scripts/ ./scripts/

# Create testdata directory and generate synthetic test invoices
# (only needed if running test_generated_invoices.py inside the container)
RUN mkdir -p testdata && python scripts/generate_test_invoices.py

# Expose the service port
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
