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

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/app/ ./app/

# Copy Built Frontend into static directory
COPY --from=frontend-builder /frontend/dist/ ./static/

# Expose Cloud Run Port
EXPOSE 8080

# Run uvicorn on $PORT
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
