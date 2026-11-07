FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir --editable .

COPY config/ ./config/
COPY skills/ ./skills/
RUN mkdir -p /app/data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).close()"

CMD ["uvicorn", "cagent_os.interfaces.http.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
