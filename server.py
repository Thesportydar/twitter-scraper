import os
import logging
from flask import Flask, jsonify
from scraper import scrape_twitter_with_cookies, init_db, save_tweets_to_db
import threading
import requests
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
N8N_AUTH_HEADER = os.getenv("N8N_AUTH_HEADER")
USERS_CDN_URL = os.getenv("USERS_CDN_URL")
MAX_TWEETS = int(os.getenv("MAX_TWEETS", 15))
MAX_IDLE_SCROLLS = int(os.getenv("MAX_IDLE_SCROLLS", 2))
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")

app = Flask(__name__)
lock = threading.Lock()

tweets_cache = []


def send_to_n8n(tweets):
    if not N8N_WEBHOOK_URL or not N8N_AUTH_HEADER:
        logger.error("Webhook URL o Auth Header no configurados en .env")
        return False
    try:
        res = requests.post(
            N8N_WEBHOOK_URL,
            json=tweets,
            headers={"Authorization": N8N_AUTH_HEADER},
            timeout=10
        )
        logger.info(f"Webhook n8n status: {res.status_code}")
        return res.ok
    except Exception as e:
        logger.error(f"Error enviando a n8n: {e}")
        return False


def get_usernames_from_cdn():
    try:
        res = requests.get(USERS_CDN_URL, timeout=10)
        res.raise_for_status()
        lines = res.text.splitlines()
        usernames = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        logger.info(f"Usuarios obtenidos del CDN: {usernames}")
        return usernames
    except Exception as e:
        logger.error(f"No se pudo obtener la lista de usuarios del CDN: {e}")
        return []


def run_scraper():
    global tweets_cache
    with lock:
        logger.info("Ejecutando scrapeo programado/manual...")
        nuevos_todos = []
        try:
            usernames = get_usernames_from_cdn()
            if not usernames:
                logger.error("No hay usuarios para scrapear. Abortando.")
                return
            init_db()
            for username in usernames:
                logger.info(f"Scrapeando @{username}... (max_tweets={MAX_TWEETS}, max_idle_scrolls={MAX_IDLE_SCROLLS}, modo_humano={MODO_HUMANO})")
                tweets = scrape_twitter_with_cookies(
                    username, max_tweets=MAX_TWEETS, max_idle_scrolls=MAX_IDLE_SCROLLS, modo_humano=MODO_HUMANO
                )
                nuevos = save_tweets_to_db(tweets, username)
                logger.info(f"{len(nuevos)} nuevos tweets")
                nuevos_todos.extend(nuevos)
            tweets_cache = nuevos_todos
            if nuevos_todos:
                send_to_n8n(nuevos_todos)
        except Exception as e:
            logger.error(f"Error en run_scraper: {e}")

@app.route("/scrape", methods=["POST"])
def manual_scrape():
    try:
        thread = threading.Thread(target=run_scraper)
        thread.start()
        return jsonify({"status": "scrape iniciado"}), 202
    except Exception as e:
        logger.error(f"Error en manual_scrape: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/tweets", methods=["GET"])
def get_tweets():
    try:
        return jsonify(tweets_cache), 200
    except Exception as e:
        logger.error(f"Error en get_tweets: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/clear_cache", methods=["POST"])
def clear_cache():
    global tweets_cache
    tweets_cache = []
    logger.info("Cache de tweets limpiada manualmente")
    return jsonify({"status": "cache limpiada"}), 200

if __name__ == "__main__":
    run_scraper()  # primer scrape inmediato
    app.run(host="0.0.0.0", port=5001)
