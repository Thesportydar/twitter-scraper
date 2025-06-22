import os
import logging
from flask import Flask, jsonify, request
from scraper import scrape_twitter_with_cookies, init_db, save_tweets_to_db, get_tweets_from_db, clear_tweets_in_db, scrape_twitter_new_only
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
MAX_TWEETS = int(os.getenv("MAX_TWEETS", 15))
MAX_IDLE_SCROLLS = int(os.getenv("MAX_IDLE_SCROLLS", 2))
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")

app = Flask(__name__)
lock = threading.Lock()


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


def run_scraper(user_configs=None):
    with lock:
        logger.info("Ejecutando scrapeo programado/manual...")
        nuevos_todos = []
        try:
            init_db()
            if user_configs is None:
                # Si tienes una lista legacy de usuarios, ponla aquí, o lanza error si no hay
                logger.error("No hay usuarios configurados para scrapeo automático. Debes pasar user_configs.")
                return
            for user_cfg in user_configs:
                username = user_cfg.get("username")
                if not username:
                    continue
                max_tweets = int(user_cfg.get("max_tweets", MAX_TWEETS))
                max_idle_scrolls = int(user_cfg.get("max_idle_scrolls", MAX_IDLE_SCROLLS))
                modo_humano = user_cfg.get("modo_humano", MODO_HUMANO)
                if isinstance(modo_humano, str):
                    modo_humano = modo_humano.lower() in ("1", "true", "yes")
                logger.info(f"Scrapeando @{username}... (max_tweets={max_tweets}, max_idle_scrolls={max_idle_scrolls}, modo_humano={modo_humano})")
                tweets = scrape_twitter_new_only(
                    username,
                    max_tweets=max_tweets,
                    max_idle_scrolls=max_idle_scrolls,
                    modo_humano=modo_humano
                )
                nuevos = save_tweets_to_db(tweets, username)
                logger.info(f"{len(nuevos)} nuevos tweets")
                nuevos_todos.extend(nuevos)
            if nuevos_todos:
                send_to_n8n(nuevos_todos)
        except Exception as e:
            logger.error(f"Error en run_scraper: {e}")


@app.route("/scrape", methods=["POST"])
def manual_scrape():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, list):
            return jsonify({"error": "El body debe ser una lista de usuarios con parámetros"}), 400
        thread = threading.Thread(target=run_scraper, args=(data,))
        thread.start()
        return jsonify({"status": "scrape iniciado"}), 202
    except Exception as e:
        logger.error(f"Error en manual_scrape: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/tweets", methods=["GET"])
def get_tweets():
    try:
        tweets = get_tweets_from_db()
        return jsonify(tweets), 200
    except Exception as e:
        logger.error(f"Error en get_tweets: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/clear_cache", methods=["POST"])
def clear_cache():
    try:
        clear_tweets_in_db()
        logger.info("Tweets borrados de la base de datos")
        return jsonify({"status": "tweets borrados de la base de datos"}), 200
    except Exception as e:
        logger.error(f"Error al borrar tweets: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    run_scraper()  # primer scrape inmediato
    app.run(host="0.0.0.0", port=5001)
