FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" python-multipart torchcrepe demucs

RUN mkdir -p /app/biaoke/lib /app/scoring_service && \
    touch /app/biaoke/__init__.py /app/biaoke/lib/__init__.py /app/scoring_service/__init__.py

COPY biaoke/lib/scoring.py /app/biaoke/lib/scoring.py
COPY scoring_service/app.py /app/scoring_service/app.py

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

CMD ["uvicorn", "scoring_service.app:app", "--host", "0.0.0.0", "--port", "8765"]
