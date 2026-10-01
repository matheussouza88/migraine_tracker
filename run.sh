#!/bin/bash

exec gunicorn -w 1 --threads 2 --bind 0.0.0.0:7070 --access-logfile - --error-logfile - "migraine_tracker:create_app()"
