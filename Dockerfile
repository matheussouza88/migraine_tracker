# Use the official Python image as the base image for building dependencies
FROM python:3.13-slim AS builder

# Set the working directory in the builder stage
WORKDIR /app

# Copy the application code and requirements to the builder stage
COPY requirements.txt ./

# Install dependencies in a separate layer
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Use a smaller base image for the final stage
FROM python:3.13.3-slim

# Install tzdata for accurate timezone support
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

# Set environment variables for minimal runtime footprint and default timezone
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Dublin

# Set the working directory in the final stage
WORKDIR /app

# Copy the installed dependencies from the builder stage
COPY --from=builder /install /usr/local

# Copy the application code to the final stage
COPY . /app

# Expose the port the app runs on
EXPOSE 7070

# Command to run the application
CMD ["bash", "run.sh"]
