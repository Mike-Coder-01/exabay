#!/bin/sh

# Stop script immediately if any command fails
set -e

echo "------------------------------------------"
echo "Applying database migrations..."
echo "------------------------------------------"

python manage.py migrate

echo "------------------------------------------"
echo "Collecting static files..."
echo "------------------------------------------"

python manage.py collectstatic --noinput

echo "------------------------------------------"
echo "Starting Gunicorn..."
echo "------------------------------------------"

# Replace shell with Gunicorn
exec "$@"