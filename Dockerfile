FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    LISTING_URL=https://www.eldorado.gg/fr/steal-a-brainrot-brainrots/i/259?lowestPrice=0&highestPrice=50&offerSortingCriterion=Price&isAscending=true&gamePageOfferIndex=1&gamePageOfferSize=50 \
    SCRAPE_IMPERSONATE=chrome \
    SCRAPE_TIMEOUT=30 \
    HOST=0.0.0.0 \
    PORT=8787

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY dashboard ./dashboard
COPY README.md ./

RUN mkdir -p /app/data/raw /app/data/normalized
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app && \
    chown -R app:app /app

USER app

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,urllib.request; port=os.getenv('PORT','8787'); url=f'http://127.0.0.1:{port}/api/healthz'; sys.exit(0 if urllib.request.urlopen(url, timeout=3).status == 200 else 1)"

CMD ["sh", "-c", "python scripts/run_dashboard.py --host ${HOST:-0.0.0.0} --port ${PORT:-8787}"]
