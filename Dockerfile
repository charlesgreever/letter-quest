FROM python:3.12-alpine

WORKDIR /app

COPY server.py /app/server.py
COPY public /app/public

RUN apk add --no-cache espeak-ng \
    && mkdir -p /data && chmod 777 /data

ENV PORT=8080 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

CMD ["python", "/app/server.py"]
