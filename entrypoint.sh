#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec daphne --proxy-headers -b 0.0.0.0 -p 8000 config.asgi:application
