# Hosted demo of BumpIn: the React frontend and the FastAPI backend in one
# service, so the whole product is one address. Built for Render's free plan
# (Docker runtime). No API key: classification and drafted emails use the
# rule-based fallbacks, EMAIL_MODE=mock means nothing is ever sent, and the
# demo data restores itself every 30 minutes.

FROM node:20-slim AS frontend
WORKDIR /frontend
COPY bumpin/frontend/package.json bumpin/frontend/package-lock.json ./
RUN npm ci
COPY bumpin/frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app/bumpin
# PyMuPDF and onnxruntime ship wheels; libgl/libglib cover RapidOCR's OpenCV.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY bumpin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bumpin/ ./
COPY --from=frontend /frontend/dist ./frontend/dist

ENV BUMPIN_PUBLIC_DEMO=1 \
    EMAIL_MODE=mock \
    LLM_PROVIDER= \
    PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT}"]
