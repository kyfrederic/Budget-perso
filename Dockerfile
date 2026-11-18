FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BUDGET_DATA_DIR=/data BUDGET_BEHIND_PROXY=1

# Lecture des tickets de caisse (sur le serveur, sans service tiers).
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home /app budget && mkdir /data && chown budget /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY budget ./budget
COPY public ./public
COPY config ./config

USER budget
VOLUME /data
EXPOSE 8000
# Un seul utilisateur : 2 processus suffisent.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "budget:create_app()"]
