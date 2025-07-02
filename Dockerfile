FROM python:3.11-slim

ENV TZ=America/Argentina/Buenos_Aires
WORKDIR /app

RUN apt-get update && apt-get install -y \
    libnss3 libatk-bridge2.0-0 libxss1 libasound2 libxcomposite1 \
    libxrandr2 libgtk-3-0 libgbm-dev tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN python -m playwright install chromium

COPY . .

EXPOSE 5000

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5001", "server:app"]
