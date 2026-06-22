FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-m", "cagent_os.interfaces.cli"]
