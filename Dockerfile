# Use the official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

# Set working directory
WORKDIR /app

# Copy dependency file and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium
RUN playwright install chromium

# Copy all project files
COPY . .

# Grant permissions (Hugging Face needs this)
RUN chmod -R 777 /app

# Expose the port Hugging Face expects
EXPOSE 7860

# Run the application (Simple command)
CMD ["python", "app.py"]