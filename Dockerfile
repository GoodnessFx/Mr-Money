# Use an official Python 3.11 image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libsqlite3-dev \
    sqlcipher \
    libsqlcipher-dev \
    git \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1001 mr_money_user

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its browser dependencies
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy project files and set ownership
COPY . .
RUN chown -R mr_money_user:mr_money_user /app

# Create logs and data directories with correct permissions
RUN mkdir -p logs data && chown -R mr_money_user:mr_money_user logs data

# Switch to non-root user
USER mr_money_user

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import src.security; src.security.health_check()"

# Run the application (default to paper mode)
CMD ["python", "src/main.py", "--mode=paper"]
