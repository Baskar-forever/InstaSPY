FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Browsers
RUN pip install playwright
RUN playwright install --with-deps chromium

COPY . .

# Render dynamically assigns a port, so we use the ENV variable
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120