# Migraine Tracker

A simple, responsive web tracker to monitor migraine episodes and medication intake (Painkiller and Sumatriptan).

## Features
- **Migraine Episode Tracking**: One-tap start and stop timer to log active migraine duration and notes.
- **Medication Logging**: Dedicated quick-action buttons to record Painkiller or Sumatriptan intake.
- **Service Discovery**: Automatic Consul service registration and HTTP health check (`/health`) on port `7070`.
- **CI/CD Integration**: Declarative `Jenkinsfile` pipeline with SCM polling, automated container testing, GHCR publishing, and GitHub Pull Request integration.

## Local Execution (Docker Compose)
```bash
docker compose up -d --build
```
The app will be available at `http://<host-ip>:7070`.

## Testing
Run tests via Docker:
```bash
docker run --rm -v $(pwd):/workspace migraine_tracker_builder pytest tests/ -v
```
