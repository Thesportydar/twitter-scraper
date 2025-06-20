FROM python:3.11-slim

WORKDIR /app
ENV TZ=America/Argentina/Buenos_Aires

RUN apt-get update && apt-get install -y wget curl git libnss3 libatk-bridge2.0-0 libxss1 libasound2 libxcomposite1 libxrandr2 libgtk-3-0 libgbm-dev tzdata

RUN pip install --no-cache-dir playwright flask apscheduler

RUN python -m playwright install --with-deps

COPY . .

EXPOSE 5000

CMD ["python", "server.py"]
