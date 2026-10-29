FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g curl && rm -rf /var/lib/apt/lists/*
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt
COPY . .
# Depuis Windows, entrypoint.sh n'est pas exécutable ; /app/media doit appartenir à app pour le volume
RUN chmod +x entrypoint.sh && mkdir -p /app/media && useradd -m app && chown -R app /app
USER app
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
