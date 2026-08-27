# Multi-stage build: Frontend + Backend into single Cloud Run container

# Stage 1: Build the React frontend.
# node:22-slim rather than -alpine: vite 8 pulls native binaries through
# rolldown and lightningcss, and the glibc builds are the well-trodden path.
# This stage is discarded in the final image, so its size does not matter.
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Backend
FROM python:3.13-slim
WORKDIR /app

# Prevent Python from writing .pyc and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Install dependencies. Runtime only -- requirements-dev.txt adds pytest, which
# has no business in a production image: it shipped ~13MB of test tooling
# (pytest, and pygments pulled in behind it) into the container that faces the
# internet.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/app/ ./app/

# Copy Built Frontend into static directory
COPY --from=frontend-builder /frontend/dist/ ./static/

# Drop root. The app writes nothing to disk -- every store is Firestore or
# in-memory -- so it needs no ownership of anything it did not bring with it.
# Cloud Run does not require this, which is exactly why it went unnoticed in a
# project whose entire argument is least privilege.
RUN useradd --create-home --uid 1000 syntrueno
USER syntrueno

# Expose Cloud Run Port
EXPOSE 8080

# Exec form, and `exec` inside it, so uvicorn REPLACES the shell and runs as
# PID 1. In shell form the shell is PID 1 and uvicorn is its child, and sh does
# not forward signals -- so Cloud Run's SIGTERM on scale-down or redeploy never
# reached uvicorn. Measured on this image before the fix: `docker stop -t 15`
# took the full 16s and the container exited 137 (SIGKILL) with no shutdown
# logged at all, rather than 143 with a graceful drain.
#
# That is not cosmetic here. A SIGKILL mid-request abandons an in-flight
# remediation between update_service and the read-back that verifies it, and
# BatchSpanProcessor never gets its shutdown flush -- the exact guarantee
# app/telemetry/tracing.py exists to make.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
