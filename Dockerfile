FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    SIDEQUEST_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 HF_HOME=/models
WORKDIR /app
COPY pyproject.toml README.md ./
COPY sidequest ./sidequest
COPY ui ./ui
COPY data ./data
RUN pip install --no-cache-dir . && \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', cache_folder='/app/models')"
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status==200 else 1)"
CMD ["uvicorn", "sidequest.api:app", "--host", "0.0.0.0", "--port", "8080"]
