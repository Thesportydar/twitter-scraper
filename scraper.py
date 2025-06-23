from playwright.sync_api import sync_playwright
import json
import os
import time
import random
import sqlite3
from datetime import datetime
import logging
from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

MAX_TWEETS = int(os.getenv("MAX_TWEETS", 15))
MAX_IDLE_SCROLLS = int(os.getenv("MAX_IDLE_SCROLLS", 2))
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")
COOKIES_FILE = "twitter_cookies.json"
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")

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
            scraped_at TEXT,
            is_retweet INTEGER,
            has_image INTEGER
        )
    """)
    conn.commit()
    conn.close()

def save_tweets_to_db(tweets, user, db_path="tweets.db"):
    """Guarda los tweets en la base de datos con batch insert."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Filtrar tweets válidos
    valid_tweets = []
    params = []
    for t in tweets:
        if not t.get("url") or not t.get("date") or not t.get("content"):
            logger.warning(f"Tweet inválido: {t}")
            continue
        
        valid_tweets.append(t)
        params.append((
            t["url"].split("/")[-1],  # id
            user,
            t["date"],
            t["url"],
            t["content"],
            datetime.now().isoformat(),
            int(t.get("is_retweet", False)),
            int(t.get("has_image", False))
        ))
    
    # Nada que insertar
    if not params:
        conn.close()
        return []
    
    # Obtener IDs existentes para devolver solo tweets nuevos
    ids_to_check = [t["url"].split("/")[-1] for t in valid_tweets]
    placeholders = ','.join(['?'] * len(ids_to_check))
    cursor.execute(f"SELECT id FROM tweets WHERE id IN ({placeholders})", ids_to_check)
    existing_ids = {row[0] for row in cursor.fetchall()}
    
    # Insertar todos en una sola operación
    cursor.executemany("""
        INSERT OR IGNORE INTO tweets (id, user, date, url, content, scraped_at, is_retweet, has_image)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, params)
    
    # Determinar cuáles fueron realmente insertados
    nuevos = [t for t in valid_tweets if t["url"].split("/")[-1] not in existing_ids]
    
    conn.commit()
    conn.close()
    return nuevos

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

def get_tweets_from_db(db_path="tweets.db"):
    """Devuelve todos los tweets almacenados en la base de datos como lista de dicts."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, user, date, url, content, scraped_at, is_retweet, has_image FROM tweets ORDER BY scraped_at DESC")
    rows = cursor.fetchall()
    conn.close()
    tweets = []
    for row in rows:
        tweets.append({
            "id": row[0],
            "user": row[1],
            "date": row[2],
            "url": row[3],
            "content": row[4],
            "scraped_at": row[5],
            "is_retweet": bool(row[6]),
            "has_image": bool(row[7])
        })
    return tweets

def clear_tweets_in_db(db_path="tweets.db"):
    """Elimina todos los tweets de la base de datos."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tweets")
    conn.commit()
    conn.close()

def get_latest_tweet_ids_from_db(username, limit=20, db_path="tweets.db"):
    """Obtiene los IDs de los últimos tweets de un usuario en la BD."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM tweets WHERE user = ? ORDER BY scraped_at DESC LIMIT ?",
        (username, limit)
    )
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return set(ids)

def scrape_twitter_new_only(username, max_tweets=15, max_idle_scrolls=2, modo_humano=True, max_consecutive_known=5, db_path="tweets.db"):
    """
    Scrapea tweets de un usuario, pero corta si encuentra varios tweets consecutivos ya existentes en la BD.
    Devuelve solo los tweets nuevos.
    """
    latest_ids = get_latest_tweet_ids_from_db(username, limit=30, db_path=db_path)
    if not os.path.exists(COOKIES_FILE):
        logger.error("⚠️ No hay cookies guardadas. Ejecutá primero login_and_save_cookies()")
        return []

    browser = None
    context = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=HEADLESS,
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

            logger.info(f"Navegando a https://x.com/{username}")
            page.goto(f"https://x.com/{username}", timeout=90000)
            if "login" in page.url:
                logger.error("⚠️ La sesión expiró. Iniciá sesión nuevamente.")
                return []

            page.wait_for_selector("[data-testid='tweet']", timeout=90000)

            tweets = []
            tweet_ids = set()
            idle_scrolls = 0
            consecutive_known = 0

            while len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls and consecutive_known < max_consecutive_known:
                tweet_elements = page.query_selector_all("[data-testid='tweet']")
                new_found = False

                for tweet in tweet_elements:
                    try:
                        link_el = tweet.query_selector('a[href*="/status/"]')
                        content_el = tweet.query_selector("[data-testid='tweetText']")
                        time_el = tweet.query_selector("time")
                        # Detectar retweet (nuevo método robusto)
                        social_context = tweet.query_selector('span[data-testid="socialContext"]')
                        is_retweet = False
                        if social_context:
                            text = social_context.inner_text().lower()
                            if "reposteó" in text or "retweeted" in text:
                                is_retweet = True
                        # Detectar imagen
                        has_image = bool(tweet.query_selector('img[src*="twimg.com/media/"]'))

                        if not (link_el and content_el and time_el):
                            continue

                        link = link_el.get_attribute('href')
                        tweet_id = link.split("/")[-1]
                        if tweet_id in tweet_ids:
                            continue
                        if tweet_id in latest_ids:
                            consecutive_known += 1
                            logger.debug(f"Tweet ya conocido: {tweet_id} ({consecutive_known} consecutivos)")
                            if consecutive_known >= max_consecutive_known:
                                logger.info(f"Encontrados {max_consecutive_known} tweets consecutivos ya existentes. Finalizando scraping.")
                                break
                            continue
                        else:
                            consecutive_known = 0

                        tweet_data = {
                            "content": content_el.inner_text(),
                            "date": time_el.get_attribute("datetime"),
                            "url": f"https://x.com{link}",
                            "is_retweet": is_retweet,
                            "has_image": has_image
                        }
                        if not tweet_data["content"] or not tweet_data["date"] or not tweet_data["url"]:
                            logger.warning(f"Tweet incompleto: {tweet_data}")
                            continue
                        tweets.append(tweet_data)
                        tweet_ids.add(tweet_id)
                        new_found = True

                        if modo_humano:
                            move_mouse_randomly_over_tweet(page, tweet)

                        if len(tweets) >= max_tweets:
                            break
                    except Exception as e:
                        logger.error(f"Error extrayendo tweet: {e}")
                        continue

                if not new_found:
                    idle_scrolls += 1
                else:
                    idle_scrolls = 0

                if len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls and consecutive_known < max_consecutive_known:
                    if modo_humano:
                        scroll_like_human(page)
                    else:
                        page.evaluate("window.scrollBy(0, window.innerHeight)")
                        time.sleep(random.uniform(1.5, 3.0))
            logger.info(f"Scraping terminado. Tweets extraídos: {len(tweets)}")
            return tweets
    except Exception as e:
        logger.error(f"Error general en scrape_twitter_new_only: {e}")
        return []
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except Exception as e:
            logger.warning(f"Error cerrando browser/context: {e}")

def scrape_multiple_users_with_cookies(user_configs, max_consecutive_known=5, db_path="tweets.db"):
    """
    Scrapea varios usuarios en una sola sesión de Playwright, devolviendo los tweets nuevos de todos.
    user_configs: lista de dicts con username, max_tweets, max_idle_scrolls, modo_humano
    """
    if not os.path.exists(COOKIES_FILE):
        logger.error("⚠️ No hay cookies guardadas. Ejecutá primero login_and_save_cookies()")
        return []

    browser = None
    context = None
    todos_nuevos = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=HEADLESS,
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
            # Cargar cookies
            with open(COOKIES_FILE, "r") as f:
                cookies = json.load(f)
            context.add_cookies(cookies)

            for user_cfg in user_configs:
                username = user_cfg.get("username")
                if not username:
                    continue
                max_tweets = int(user_cfg.get("max_tweets", 15))
                max_idle_scrolls = int(user_cfg.get("max_idle_scrolls", 2))
                modo_humano = user_cfg.get("modo_humano", True)
                if isinstance(modo_humano, str):
                    modo_humano = modo_humano.lower() in ("1", "true", "yes")
                logger.info(f"Scrapeando @{username}... (max_tweets={max_tweets}, max_idle_scrolls={max_idle_scrolls}, modo_humano={modo_humano})")

                latest_ids = get_latest_tweet_ids_from_db(username, limit=30, db_path=db_path)
                page = context.new_page()
                try:
                    page.goto(f"https://x.com/{username}", timeout=90000)
                    if "login" in page.url:
                        logger.error("⚠️ La sesión expiró. Iniciá sesión nuevamente.")
                        continue
                    page.wait_for_selector("[data-testid='tweet']", timeout=90000)

                    tweets = []
                    tweet_ids = set()
                    idle_scrolls = 0
                    consecutive_known = 0

                    while len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls and consecutive_known < max_consecutive_known:
                        tweet_elements = page.query_selector_all("[data-testid='tweet']")
                        new_found = False
                        for tweet in tweet_elements:
                            try:
                                link_el = tweet.query_selector('a[href*="/status/"]')
                                content_el = tweet.query_selector("[data-testid='tweetText']")
                                time_el = tweet.query_selector("time")
                                # Detectar retweet (nuevo método robusto)
                                social_context = tweet.query_selector('span[data-testid="socialContext"]')
                                is_retweet = False
                                if social_context:
                                    text = social_context.inner_text().lower()
                                    if "reposteó" in text or "retweeted" in text:
                                        is_retweet = True
                                has_image = bool(tweet.query_selector('img[src*="twimg.com/media/"]'))
                                if not (link_el and content_el and time_el):
                                    continue
                                link = link_el.get_attribute('href')
                                tweet_id = link.split("/")[-1]
                                if tweet_id in tweet_ids:
                                    continue
                                if tweet_id in latest_ids:
                                    consecutive_known += 1
                                    if consecutive_known >= max_consecutive_known:
                                        logger.info(f"Encontrados {max_consecutive_known} tweets consecutivos ya existentes para @{username}. Finalizando scraping.")
                                        break
                                    continue
                                else:
                                    consecutive_known = 0
                                tweet_data = {
                                    "content": content_el.inner_text(),
                                    "date": time_el.get_attribute("datetime"),
                                    "url": f"https://x.com{link}",
                                    "is_retweet": is_retweet,
                                    "has_image": has_image
                                }
                                if not tweet_data["content"] or not tweet_data["date"] or not tweet_data["url"]:
                                    logger.warning(f"Tweet incompleto: {tweet_data}")
                                    continue
                                tweets.append(tweet_data)
                                tweet_ids.add(tweet_id)
                                new_found = True
                                if modo_humano:
                                    move_mouse_randomly_over_tweet(page, tweet)
                                if len(tweets) >= max_tweets:
                                    break
                            except Exception as e:
                                logger.error(f"Error extrayendo tweet: {e}")
                                continue
                        if not new_found:
                            idle_scrolls += 1
                        else:
                            idle_scrolls = 0
                        if len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls and consecutive_known < max_consecutive_known:
                            if modo_humano:
                                scroll_like_human(page)
                            else:
                                page.evaluate("window.scrollBy(0, window.innerHeight)")
                                time.sleep(random.uniform(1.5, 3.0))
                    nuevos = save_tweets_to_db(tweets, username, db_path=db_path)
                    logger.info(f"{len(nuevos)} nuevos tweets para @{username}")
                    todos_nuevos.extend(nuevos)
                except Exception as e:
                    logger.error(f"Error scrapeando @{username}: {e}")
                finally:
                    page.close()
            return todos_nuevos
    except Exception as e:
        logger.error(f"Error general en scrape_multiple_users_with_cookies: {e}")
        return []
    finally:
        try:
            if context:
                context.close()
            if browser:
                browser.close()
        except Exception as e:
            logger.warning(f"Error cerrando browser/context: {e}")

# Ejemplo de uso
if __name__ == "__main__":
    # PASO 1: Ejecutar solo una vez para guardar cookies
    login_and_save_cookies()
    exit(0)
    
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
    nuevos_tweets = save_tweets_to_db(tweets, username)
    print(f"\n✅ {len(nuevos_tweets)} tweets nuevos guardados en la base de datos.")
