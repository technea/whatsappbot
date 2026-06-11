FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn requests

COPY bot.py .

CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "9000"]
