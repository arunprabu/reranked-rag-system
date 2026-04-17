FROM python:3.13-slim

WORKDIR /app

# Install system dependencies required for building some python packages / PostgreSQL clients
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency resolution (optional but good practice)
RUN pip install uv

# Copy pyproject.toml first to leverage Docker cache
COPY pyproject.toml .

# Install dependencies directly using pip with pyproject.toml
RUN uv pip install --system -e .

COPY . .

# Expose port
EXPOSE 8000

# Command to run the application is specified in compose file, but keep it here as default
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]