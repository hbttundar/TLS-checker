FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BIN=/usr/bin/chromium-browser \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    PATH="/home/bot/.local/bin:$PATH"

WORKDIR /app

# Install chromium & minimal runtime deps
RUN apk add --no-cache \
    chromium chromium-chromedriver \
    nss freetype harfbuzz ca-certificates ttf-freefont \
    libstdc++ bash curl && \
    adduser -D -h /home/bot bot && \
    mkdir -p /data/chrome_profile && chown -R bot:bot /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R bot:bot /app

USER bot

VOLUME ["/data"]
ENV USER_DATA_DIR=/data/chrome_profile \
    SUBSCRIBERS_FILE=/data/subscribers.json \
    HEADLESS=true \
    LOG_LEVEL=INFO \
    ENVIRONMENT=production

CMD ["python", "bot.py"]
