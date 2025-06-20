from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
from scraper import scrape_twitter_with_cookies, init_db, save_tweets_to_db
import threading

app = Flask(__name__)
lock = threading.Lock()

# Usuarios a scrapear
USERNAMES = ["dosinaga2", "TraderX3AL30", "cristiannmillo"]
tweets_cache = []

def run_scraper():
    global tweets_cache
    with lock:
        print("🔁 Ejecutando scrapeo programado/manual...")
        nuevos_todos = []
        init_db()
        for username in USERNAMES:
            print(f"🔍 Scrapeando @{username}...")
            tweets = scrape_twitter_with_cookies(
                username, max_tweets=15, max_idle_scrolls=2, modo_humano=True
            )
            nuevos = save_tweets_to_db(tweets, username)
            print(f"🆕 {len(nuevos)} nuevos tweets")
            nuevos_todos.extend(nuevos)
        tweets_cache = nuevos_todos

scheduler = BackgroundScheduler()
scheduler.add_job(run_scraper, "interval", hours=6)
scheduler.start()

@app.route("/scrape", methods=["POST"])
def manual_scrape():
    thread = threading.Thread(target=run_scraper)
    thread.start()
    return jsonify({"status": "scrape iniciado"}), 202

@app.route("/tweets", methods=["GET"])
def get_tweets():
    return jsonify(tweets_cache), 200

if __name__ == "__main__":
    run_scraper()  # primer scrape inmediato
    app.run(host="0.0.0.0", port=5000)
