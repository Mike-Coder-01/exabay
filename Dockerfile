# -----------------------------------------------------------------------------
# Base Image
# -----------------------------------------------------------------------------
# Start from the official lightweight Python 3.12 image.
# This image already contains:
# - Linux
# - Python
# - pip
#
FROM python:3.12-slim

# -----------------------------------------------------------------------------
# Working Directory
# -----------------------------------------------------------------------------
# Every command after this will execute inside /app.
#
WORKDIR /app

# -----------------------------------------------------------------------------
# Copy only requirements first
# -----------------------------------------------------------------------------
# We copy requirements.txt before the rest of the project.
#
# Why?
# Docker caches image layers.
#
# If your source code changes but requirements.txt doesn't,
# Docker won't reinstall every package.
#
COPY requirements.txt .

# -----------------------------------------------------------------------------
# Install Python packages
# -----------------------------------------------------------------------------
#
# --no-cache-dir prevents pip from storing downloaded package archives,
# making the image smaller.
#
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Copy application source code
# -----------------------------------------------------------------------------
#
# Now copy everything else into the container.
#
COPY . .

# -----------------------------------------------------------------------------
# Make entrypoint executable
# -----------------------------------------------------------------------------
#
RUN chmod +x entrypoint.sh

# -----------------------------------------------------------------------------
# Container startup
# -----------------------------------------------------------------------------
#
# ENTRYPOINT performs startup tasks
# CMD provides the default application command
#
ENTRYPOINT ["./entrypoint.sh"]

CMD ["gunicorn", "exabay.wsgi:application", "--bind", "0.0.0.0:8000"]