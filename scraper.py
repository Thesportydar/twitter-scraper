from playwright.sync_api import sync_playwright
import json
import os
import time
import random
import sqlite3
from datetime import datetime


def init_db(db_path="tweets.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            user TEXT,
            date TEXT,
            url TEXT,
            content TEXT,
            scraped_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_tweets_to_db(tweets, user, db_path="tweets.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for t in tweets:
        try:
            cursor.execute("""
                INSERT INTO tweets (id, user, date, url, content, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                t["url"].split("/")[-1],
                user,
                t["date"],
                t["url"],
                t["content"],
                datetime.now().isoformat()
            ))
        except sqlite3.IntegrityError:
            # Ya estaba
            continue
    conn.commit()
    conn.close()

COOKIES_FILE = "twitter_cookies.json"

def login_and_save_cookies():
    """Inicia sesión manualmente y guarda las cookies para reutilización"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        print(">>> Por favor inicia sesión manualmente en Twitter...")
        page.goto("https://x.com/login", timeout=60000)
        
        # Esperar hasta que se detecte el inicio de sesión
        page.wait_for_url("https://x.com/home", timeout=0)  # timeout=0 espera indefinidamente
        
        # Guardar cookies en archivo
        cookies = context.cookies()
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f)
        
        print(f"✅ Cookies guardadas en {COOKIES_FILE}")
        browser.close()

def scroll_like_human(page):
    """Simula un comportamiento de scroll más humano"""
    for _ in range(random.randint(3, 6)):
        page.mouse.wheel(0, random.randint(200, 400))  # scroll hacia abajo
        time.sleep(random.uniform(0.3, 1.2))

    if random.random() < 0.3:  # 30% de probabilidad de distraerse
        print("🤫 Pausa humana aleatoria")
        time.sleep(random.uniform(4, 8))


def move_mouse_randomly_over_tweet(page, tweet):
    """Mueve el mouse a un punto aleatorio dentro de un tweet"""
    try:
        box = tweet.bounding_box()
        if box:
            x = box['x'] + random.randint(10, int(box['width']) - 10)
            y = box['y'] + random.randint(10, int(box['height']) - 10)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            time.sleep(random.uniform(0.2, 0.6))
    except:
        pass


def scrape_twitter_with_cookies(username, max_tweets=5, max_idle_scrolls=10, modo_humano=True):
    if not os.path.exists(COOKIES_FILE):
        print("⚠️ No hay cookies guardadas. Ejecutá primero login_and_save_cookies()")
        return []

    with sync_playwright() as p:
        #browser = p.chromium.launch(headless=False)
        #context = browser.new_context()

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
        (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
        )
        page = context.new_page()

        # Cargar cookies
        with open(COOKIES_FILE, "r") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)

        # Ir al perfil
        page.goto(f"https://x.com/{username}", timeout=15000)
        if "login" in page.url:
            print("⚠️ La sesión expiró. Iniciá sesión nuevamente.")
            return []

        page.wait_for_selector("[data-testid='tweet']", timeout=10000)

        tweets = []
        tweet_ids = set()
        idle_scrolls = 0

        while len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls:
            tweet_elements = page.query_selector_all("[data-testid='tweet']")
            new_found = False

            for tweet in tweet_elements:
                try:
                    link_el = tweet.query_selector('a[href*="/status/"]')
                    content_el = tweet.query_selector("[data-testid='tweetText']")
                    time_el = tweet.query_selector("time")

                    if not (link_el and content_el and time_el):
                        continue

                    link = link_el.get_attribute('href')
                    tweet_id = link.split("/")[-1]
                    if tweet_id in tweet_ids:
                        continue

                    tweets.append({
                        "content": content_el.inner_text(),
                        "date": time_el.get_attribute("datetime"),
                        "url": f"https://x.com{link}",
                    })
                    tweet_ids.add(tweet_id)
                    new_found = True

                    if modo_humano:
                        move_mouse_randomly_over_tweet(page, tweet)

                    if len(tweets) >= max_tweets:
                        break
                except:
                    continue

            if not new_found:
                idle_scrolls += 1
            else:
                idle_scrolls = 0

            if len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls:
                if modo_humano:
                    scroll_like_human(page)
                else:
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                    time.sleep(random.uniform(1.5, 3.0))

        browser.close()
        return tweets


# Ejemplo de uso
if __name__ == "__main__":
    # PASO 1: Ejecutar solo una vez para guardar cookies
    # login_and_save_cookies()
    
    # PASO 2: Scrapear usando cookies guardadas
    username = "dosinaga2"
    tweets = scrape_twitter_with_cookies(username, max_tweets=15, max_idle_scrolls=2)
    
    print(f"\nÚltimos tweets de @{username}:")
    for i, tweet in enumerate(tweets, 1):
        print(f"\n--- TWEET {i} [{tweet['date']}] ---")
        print(tweet["content"])
        print(f"URL: {tweet['url']}")

    # Guardar en la base de datos
    init_db()
    save_tweets_to_db(tweets, username)
    print(f"\n✅ {len(tweets)} tweets guardados en la base de datos.")
