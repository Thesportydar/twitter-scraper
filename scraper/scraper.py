from playwright.sync_api import sync_playwright
import json
import os
import time
import random
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import collections
import re
from io import BytesIO

import pyarrow as pa
import pyarrow.parquet as pq


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MAX_TWEETS = int(os.getenv("MAX_TWEETS", 15))
MAX_IDLE_SCROLLS = int(os.getenv("MAX_IDLE_SCROLLS", 2))
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "Tweet")
S3_BUCKET = os.getenv("S3_BUCKET")
EVENT_BUS_NAME = os.getenv("EVENT_BUS_NAME", "default")

LOCAL_TEST = os.getenv("LOCAL_TEST", "false").lower() in ("true", "1", "yes")
COOKIES_FILE = "cookies.json"
LOCAL_DB_FILE = "local_dynamodb.json"

def read_local_db():
    if os.path.exists(LOCAL_DB_FILE):
        try:
            with open(LOCAL_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error al leer {LOCAL_DB_FILE}: {e}")
    return []

def write_local_db(tweets):
    try:
        with open(LOCAL_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error al escribir en {LOCAL_DB_FILE}: {e}")

# Tweet URL pattern: https://x.com/{user_handle}/status/{tweet_id}
URL_PATTERN = re.compile(r"x\.com/([^/]+)/status/(\d+)")

# Parquet schema — must match the Athena table in athena_tweets.sql
PARQUET_SCHEMA = pa.schema([
    pa.field("tweet_id",         pa.string()),
    pa.field("user_handle",      pa.string()),
    pa.field("content",          pa.string()),
    pa.field("tweet_timestamp",  pa.timestamp("us", tz="UTC")),
    pa.field("crawl_timestamp",  pa.timestamp("us", tz="UTC")),
    pa.field("is_retweet",       pa.bool_()),
    pa.field("has_image",        pa.bool_()),
    pa.field("url",              pa.string()),
    pa.field("crawl_year",       pa.int32()),
    pa.field("crawl_month",      pa.int32()),
    pa.field("crawl_day",        pa.int32()),
    pa.field("tweet_year",       pa.int32()),
    pa.field("tweet_month",      pa.int32()),
    pa.field("tweet_day",        pa.int32()),
])

def send_cloudwatch_metrics(metrics):
    """Envía métricas a CloudWatch para monitoreo."""
    if LOCAL_TEST:
        logger.info(f"[LOCAL TEST] Métricas de CloudWatch simuladas: {metrics}")
        return
    try:
        cw = boto3.client('cloudwatch')
        metric_data = []
        for name, value in metrics.items():
            metric_data.append({
                'MetricName': name,
                'Value': value,
                'Unit': 'Count'
            })
        
        if metric_data:
            cw.put_metric_data(
                Namespace=os.getenv("CW_NAMESPACE", "TwitterScraper"),
                MetricData=metric_data
            )
    except Exception as e:
        logger.error(f"Error enviando métricas a CloudWatch: {e}")

def upload_parquet_to_s3(tweets, now, s3):
    """
    Escribe un Parquet Snappy en processed/ con el schema limpio para Athena.
    El nombre de archivo coincide con el JSON en data/ para facilitar correlación.
    Fallo aislado: un error aquí no corta el flujo principal.
    """
    crawl_ts    = now.astimezone(timezone.utc)
    crawl_year  = now.year
    crawl_month = now.month
    crawl_day   = now.day

    tweet_ids, user_handles, contents          = [], [], []
    tweet_timestamps, crawl_timestamps         = [], []
    is_retweets, has_images, urls              = [], [], []
    c_years, c_months, c_days                  = [], [], []
    t_years, t_months, t_days                  = [], [], []

    for t in tweets:
        url = t.get("url") or ""
        m = URL_PATTERN.search(url)
        user_handle = m.group(1) if m else None
        tweet_id    = m.group(2) if m else None

        date_str = t.get("date") or ""
        try:
            tweet_ts = datetime.fromisoformat(
                date_str.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (ValueError, AttributeError):
            tweet_ts = None

        tweet_ids.append(tweet_id)
        user_handles.append(user_handle)
        contents.append(t.get("content"))
        tweet_timestamps.append(tweet_ts)
        crawl_timestamps.append(crawl_ts)
        is_retweets.append(bool(t.get("is_retweet")))
        has_images.append(bool(t.get("has_image")))
        urls.append(url)
        c_years.append(crawl_year)
        c_months.append(crawl_month)
        c_days.append(crawl_day)
        t_years.append(tweet_ts.year   if tweet_ts else None)
        t_months.append(tweet_ts.month if tweet_ts else None)
        t_days.append(tweet_ts.day     if tweet_ts else None)

    table = pa.table(
        {
            "tweet_id":        tweet_ids,
            "user_handle":     user_handles,
            "content":         contents,
            "tweet_timestamp": pa.array(tweet_timestamps, type=pa.timestamp("us", tz="UTC")),
            "crawl_timestamp": pa.array(crawl_timestamps, type=pa.timestamp("us", tz="UTC")),
            "is_retweet":      is_retweets,
            "has_image":       has_images,
            "url":             urls,
            "crawl_year":      pa.array(c_years,   type=pa.int32()),
            "crawl_month":     pa.array(c_months,  type=pa.int32()),
            "crawl_day":       pa.array(c_days,    type=pa.int32()),
            "tweet_year":      pa.array(t_years,   type=pa.int32()),
            "tweet_month":     pa.array(t_months,  type=pa.int32()),
            "tweet_day":       pa.array(t_days,    type=pa.int32()),
        },
        schema=PARQUET_SCHEMA,
    )

    buf = BytesIO()
    pq.write_table(table, buf, compression="snappy")

    file_name = f"tweets_{now.strftime('%H-%M-%S')}.parquet"
    key = f"processed/crawl_year={crawl_year}/crawl_month={crawl_month}/{file_name}"
    
    if LOCAL_TEST:
        local_path = os.path.join("local_s3", key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(buf.getvalue())
        logger.info(f"[LOCAL TEST] Parquet escrito localmente: {local_path} ({len(tweets)} tweets)")
    else:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=buf.getvalue())
        logger.info(f"Parquet escrito: s3://{S3_BUCKET}/{key} ({len(tweets)} tweets)")


def upload_to_s3(tweets):
    """Sube todos los tweets de la ejecución a S3 (o los guarda localmente si LOCAL_TEST es True)."""
    if not tweets or (not S3_BUCKET and not LOCAL_TEST):
        return

    s3 = None if LOCAL_TEST else boto3.client('s3')
    # Usar explícitamente hora Argentina
    tz_arg = ZoneInfo("America/Argentina/Buenos_Aires")
    now = datetime.now(tz_arg)

    try:
        # Estructura: year=YYYY/month=MM/day=DD/tweets_HH-MM-SS.json
        file_name = f"tweets_{now.strftime('%H-%M-%S')}.json"
        key = f"data/year={now.year}/month={now.month:02d}/day={now.day:02d}/{file_name}"

        if LOCAL_TEST:
            local_path = os.path.join("local_s3", key)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                json.dump(tweets, f, ensure_ascii=False, indent=2)
            logger.info(f"[LOCAL TEST] JSON escrito localmente: {local_path} ({len(tweets)} tweets)")
        else:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=json.dumps(tweets, ensure_ascii=False),
                ContentType='application/json'
            )
            logger.info(f"Subidos {len(tweets)} tweets a s3://{S3_BUCKET}/{key}")

        # Enviar evento a EventBridge
        event_payload = {
            "bucket": S3_BUCKET or "local-bucket",
            "s3Key": key,
            "count": len(tweets),
            "status": "ok"
        }

        if LOCAL_TEST:
            logger.info(f"[LOCAL TEST] Evento EventBridge simulado: {event_payload}")
        else:
            eb = boto3.client('events')
            eb.put_events(
                Entries=[
                    {
                        'Source': 'twitter.scraper',
                        'DetailType': 'TweetsUploaded',
                        'Detail': json.dumps(event_payload),
                        'EventBusName': EVENT_BUS_NAME
                    }
                ]
            )
            logger.info(f"Evento enviado a EventBridge: {event_payload}")

    except Exception as e:
        logger.error(f"Error subiendo a S3 o enviando evento: {e}")

    # Escribir Parquet limpio para Athena — fallo aislado, no corta el flujo principal
    try:
        upload_parquet_to_s3(tweets, now, s3)
    except Exception as e:
        logger.error(f"Error escribiendo Parquet: {e}")

def save_tweets_to_db(tweets, user):
    """Guarda los tweets en DynamoDB (o local DB si LOCAL_TEST es True) con batch insert y TTL de 72hs."""
    # Filtrar tweets válidos
    valid_tweets = []
    for t in tweets:
        if not t.get("url") or not t.get("date") or not t.get("content"):
            logger.warning(f"Tweet inválido: {t}")
            continue
        valid_tweets.append(t)
    
    if not valid_tweets:
        return []
    
    # Obtener IDs existentes para devolver solo tweets nuevos
    ids_to_check = [t["url"].split("/")[-1] for t in valid_tweets]
    existing_ids = set()
    read_errors = 0
    
    if LOCAL_TEST:
        local_tweets = read_local_db()
        existing_ids = {t["Id"] for t in local_tweets if t["Id"] in ids_to_check}
    else:
        # Batch get para verificar existencia (limitado a 100 items por request, aquí asumimos <100)
        if ids_to_check:
            try:
                dynamodb = boto3.resource('dynamodb')
                # DynamoDB batch_get_item requiere claves únicas
                unique_ids = list(set(ids_to_check))
                # Procesar en chunks de 100 si fuera necesario, pero MAX_TWEETS es bajo
                response = dynamodb.batch_get_item(
                    RequestItems={
                        DYNAMODB_TABLE: {
                            'Keys': [{'Id': i} for i in unique_ids],
                            'ProjectionExpression': 'Id'
                        }
                    }
                )
                existing_ids = {item['Id'] for item in response['Responses'].get(DYNAMODB_TABLE, [])}
            except Exception as e:
                logger.error(f"Error verificando existencia de tweets: {e}")
                read_errors = 1

    nuevos = []
    write_errors = 0
    
    if LOCAL_TEST:
        try:
            local_tweets = read_local_db()
            for t in valid_tweets:
                t_id = t["url"].split("/")[-1]
                if t_id not in existing_ids:
                    # TTL: 72 horas desde ahora
                    expire_at = int((datetime.now() + timedelta(hours=72)).timestamp())
                    item = {
                        'Id': t_id,
                        'User': user,
                        'Date': t['date'],
                        'Url': t['url'],
                        'Content': t['content'],
                        'ScrapedAt': datetime.now().isoformat(),
                        'IsRetweet': int(t.get("is_retweet", False)),
                        'HasImage': int(t.get("has_image", False)),
                        'ExpireAt': expire_at
                    }
                    local_tweets.append(item)
                    nuevos.append(t)
                    existing_ids.add(t_id) # Evitar duplicados en el mismo batch
            write_local_db(local_tweets)
        except Exception as e:
            logger.error(f"Error guardando tweets localmente: {e}")
            write_errors = 1
    else:
        try:
            dynamodb = boto3.resource('dynamodb')
            table = dynamodb.Table(DYNAMODB_TABLE)
            with table.batch_writer() as batch:
                for t in valid_tweets:
                    t_id = t["url"].split("/")[-1]
                    if t_id not in existing_ids:
                        # TTL: 72 horas desde ahora
                        expire_at = int((datetime.now() + timedelta(hours=72)).timestamp())
                        
                        item = {
                            'Id': t_id,
                            'User': user,
                            'Date': t['date'],
                            'Url': t['url'],
                            'Content': t['content'],
                            'ScrapedAt': datetime.now().isoformat(),
                            'IsRetweet': int(t.get("is_retweet", False)),
                            'HasImage': int(t.get("has_image", False)),
                            'ExpireAt': expire_at
                        }
                        batch.put_item(Item=item)
                        nuevos.append(t)
                        existing_ids.add(t_id) # Evitar duplicados en el mismo batch
        except Exception as e:
            logger.error(f"Error guardando tweets en DynamoDB: {e}")
            write_errors = 1
        
    # Enviar métricas
    try:
        skipped_count = len(valid_tweets) - len(nuevos)
        metrics = {
            'TweetsScraped': len(valid_tweets),
            'TweetsInserted': len(nuevos),
            'TweetsSkipped': skipped_count, # "Lecturas al pedo" (ya existían)
            'DynamoDBReadErrors': read_errors,
            'DynamoDBWriteErrors': write_errors
        }
        send_cloudwatch_metrics(metrics)
        logger.info(f"Métricas enviadas: {json.dumps(metrics)}")
    except Exception as e:
        logger.warning(f"No se pudieron calcular/enviar métricas: {e}")
        
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



def get_tweets_from_db():
    """Devuelve todos los tweets almacenados en DynamoDB (o local DB si LOCAL_TEST es True)."""
    if LOCAL_TEST:
        local_tweets = read_local_db()
        local_tweets.sort(key=lambda x: x.get('ScrapedAt', ''), reverse=True)
        tweets = []
        for item in local_tweets:
            tweets.append({
                "id": item['Id'],
                "user": item.get('User'),
                "date": item.get('Date'),
                "url": item.get('Url'),
                "content": item.get('Content'),
                "scraped_at": item.get('ScrapedAt'),
                "is_retweet": bool(item.get('IsRetweet')),
                "has_image": bool(item.get('HasImage'))
            })
        return tweets

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(DYNAMODB_TABLE)
    try:
        # Scan es costoso, usar con cuidado
        response = table.scan()
        items = response.get('Items', [])
        # Paginación si hay muchos
        while 'LastEvaluatedKey' in response:
            response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
            items.extend(response.get('Items', []))
            
        # Ordenar en memoria por scraped_at DESC
        items.sort(key=lambda x: x.get('ScrapedAt', ''), reverse=True)
        
        tweets = []
        for item in items:
            tweets.append({
                "id": item['Id'],
                "user": item.get('User'),
                "date": item.get('Date'),
                "url": item.get('Url'),
                "content": item.get('Content'),
                "scraped_at": item.get('ScrapedAt'),
                "is_retweet": bool(item.get('IsRetweet')),
                "has_image": bool(item.get('HasImage'))
            })
        return tweets
    except Exception as e:
        logger.error(f"Error obteniendo tweets de DynamoDB: {e}")
        return []

def get_latest_tweet_ids_from_db(username, limit=20):
    """Obtiene los IDs de los últimos tweets de un usuario en DynamoDB (o local DB si LOCAL_TEST es True)."""
    if LOCAL_TEST:
        local_tweets = read_local_db()
        user_tweets = [t for t in local_tweets if t.get("User") == username]
        user_tweets.sort(key=lambda x: x.get('ScrapedAt', ''), reverse=True)
        ids = [t['Id'] for t in user_tweets[:limit]]
        return set(ids)

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(DYNAMODB_TABLE)
    try:
        response = table.query(
            IndexName='UserIndex',
            KeyConditionExpression=Key('User').eq(username),
            ScanIndexForward=False, # DESC order
            Limit=limit,
            ProjectionExpression='Id'
        )
        ids = [item['Id'] for item in response.get('Items', [])]
        return set(ids)
    except Exception as e:
        # Si la tabla no existe o error
        logger.warning(f"No se pudieron obtener tweets previos para {username}: {e}")
        return set()

async def get_full_tweet_text(tweet_el, tweet_url: str, context) -> str:
    """
    Devuelve el texto completo del tweet.
    Si detecta el botón 'Mostrar más' (tweet truncado), abre la URL del tweet
    en una pestaña nueva y extrae el PRIMER tweetText (el del tweet principal,
    no los comentarios). Siempre cierra la pestaña al terminar.
    Fallback: texto truncado del timeline si la pestaña falla.
    """
    show_more = await tweet_el.query_selector('[data-testid="tweet-text-show-more-link"]')

    if not show_more:
        content_el = await tweet_el.query_selector('[data-testid="tweetText"]')
        return (await content_el.inner_text()) if content_el else ""

    logger.info(f"Tweet truncado detectado, abriendo {tweet_url} para obtener texto completo...")
    detail_page = None
    try:
        detail_page = await context.new_page()
        await detail_page.goto(tweet_url, timeout=30000)
        await detail_page.wait_for_selector('[data-testid="tweetText"]', timeout=15000, state="visible")
        # El primer tweetText es siempre el tweet principal; los comentarios van después
        content_el = await detail_page.query_selector('[data-testid="tweetText"]')
        return (await content_el.inner_text()) if content_el else ""
    except Exception as e:
        logger.warning(f"No se pudo obtener texto completo de {tweet_url}: {e}")
        content_el = await tweet_el.query_selector('[data-testid="tweetText"]')
        return (await content_el.inner_text()) if content_el else ""
    finally:
        if detail_page:
            await detail_page.close()


async def async_scrape_multiple_users_with_stealth(user_configs, cookies, max_consecutive_known=5):
    """
    Scrapea varios usuarios en una sola sesión de Playwright usando playwright-stealth (async), devolviendo los tweets nuevos de todos.
    user_configs: lista de dicts con username, max_tweets, max_idle_scrolls, modo_humano
    cookies: lista de dicts con las cookies
    """
    if not cookies:
        logger.error("⚠️ No se proporcionaron cookies.")
        return []

    todos_nuevos = []
    browser = None
    context = None
    page = None
    # --- FIFO queue y contador de reintentos por usuario ---
    user_cfgs_random = user_configs[:]
    random.shuffle(user_cfgs_random)
    user_queue = collections.deque(user_cfgs_random)
    retry_counts = {cfg.get("username"): 0 for cfg in user_cfgs_random if cfg.get("username")}
    max_retries = 2
    try:
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
            # Cargar cookies
            await context.add_cookies(cookies)
            page = await context.new_page()
            while user_queue:
                user_cfg = user_queue.popleft()
                username = user_cfg.get("username")
                if not username:
                    continue
                max_tweets = int(user_cfg.get("max_tweets", 15))
                max_idle_scrolls = int(user_cfg.get("max_idle_scrolls", 2))
                modo_humano = user_cfg.get("modo_humano", True)
                if isinstance(modo_humano, str):
                    modo_humano = modo_humano.lower() in ("1", "true", "yes")
                logger.info(f"Scrapeando @{username}... (max_tweets={max_tweets}, max_idle_scrolls={max_idle_scrolls}, modo_humano={modo_humano})")
                latest_ids = get_latest_tweet_ids_from_db(username, limit=30)
                retries = retry_counts.get(username, 0)
                try:
                    await page.goto(f"https://x.com/{username}", timeout=120000)
                    logger.info(f"URL tras goto: {page.url}")
                    # Si la URL no contiene el username, probablemente hubo redirección
                    if (username.lower() not in page.url.lower()) or any(x in page.url for x in ["login", "unsupported-browser", "consent", "challenge", "error"]):
                        logger.error(f"⚠️ Redirección/bloqueo detectado para @{username} (url: {page.url}). Saltando usuario y recreando contexto.")
                        await page.close()
                        await context.close()
                        context = await browser.new_context()
                        await context.add_cookies(cookies)
                        page = await context.new_page()
                        raise Exception("Redirección/bloqueo detectado")
                    try:
                        await page.wait_for_selector("[data-testid='tweet']", timeout=30000, state="visible")
                    except Exception as e:
                        logger.error(f"No se encontró el selector de tweets para @{username} (url: {page.url}). Error: {e}. Saltando usuario y recreando contexto.")
                        await page.close()
                        await context.close()
                        context = await browser.new_context()
                        await context.add_cookies(cookies)
                        page = await context.new_page()
                        raise Exception("No se encontró el selector de tweets")
                    #logger.info(f"Esperando tweets de @{username}...")
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    tweets = []
                    tweet_ids = set()
                    idle_scrolls = 0
                    consecutive_known = 0
                    while len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls and consecutive_known < max_consecutive_known:
                        tweet_elements = await page.query_selector_all("[data-testid='tweet']")
                        new_found = False
                        for tweet in tweet_elements:
                            try:
                                link_el = await tweet.query_selector('a[href*="/status/"]')
                                content_el = await tweet.query_selector("[data-testid='tweetText']")
                                time_el = await tweet.query_selector("time")
                                social_context = await tweet.query_selector('span[data-testid="socialContext"]')
                                is_retweet = False
                                if social_context:
                                    text = (await social_context.inner_text()).lower()
                                    if "reposteó" in text or "retweeted" in text:
                                        is_retweet = True
                                has_image = bool(await tweet.query_selector('img[src*="twimg.com/media/"]'))
                                if not (link_el and content_el and time_el):
                                    continue
                                link = await link_el.get_attribute('href')
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
                                    "content": await get_full_tweet_text(tweet, f"https://x.com{link}", context),
                                    "date": await time_el.get_attribute("datetime"),
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
                            # Scrollear siempre; modo_humano solo afecta el timing de la pausa
                            await page.evaluate("window.scrollBy(0, window.innerHeight)")
                            pause = random.uniform(1.2, 2.5) if modo_humano else random.uniform(0.8, 1.5)
                            await asyncio.sleep(pause)
                    nuevos = save_tweets_to_db(tweets, username)
                    logger.info(f"{len(nuevos)} nuevos tweets para @{username}")
                    todos_nuevos.extend(nuevos)
                except Exception as e:
                    logger.error(f"Error scrapeando @{username} (intento {retries+1}): {e}")
                    # try:
                    #     screenshot_path = f"screenshot_{username}_{int(time.time())}.png"
                    #     await page.screenshot(path=screenshot_path)
                    #     logger.error(f"Captura de pantalla guardada: {screenshot_path}")
                    # except Exception as se:
                    #     logger.error(f"No se pudo guardar screenshot: {se}")
                    retries += 1
                    retry_counts[username] = retries
                    if retries <= max_retries:
                        logger.info(f"Reinsertando @{username} al final de la cola (reintento {retries}/{max_retries})...")
                        user_queue.append(user_cfg)
                    else:
                        logger.error(f"Fallo definitivo scrapeando @{username}")
                    # Espera antes de reintentar
                    await asyncio.sleep(5 + 5*retries)
            
            # Subir todos los tweets nuevos de esta sesión a S3
            if todos_nuevos:
                upload_to_s3(todos_nuevos)
                
            return todos_nuevos
    except Exception as e:
        logger.error(f"Error general en async_scrape_multiple_users_with_stealth: {e}")
        return []
    finally:
        try:
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()
        except Exception as e:
            logger.warning(f"Error cerrando browser/context: {e}")

async def async_scrape_feed_with_stealth(cookies, max_tweets=100, max_idle_scrolls=5):
    """
    Scrapea el feed 'Following' de /home hasta max_tweets tweets.
    Intenta hacer click en la pestaña 'Following' con múltiples selectores XPath.
    Si ninguno funciona, usa el feed que esté activo por defecto.
    """
    if not cookies:
        logger.error("⚠️ No se proporcionaron cookies.")
        return []

    # Selectores para la pestaña Following — intentados en orden
    FOLLOWING_TAB_XPATHS = [
        "xpath=//nav[@role='navigation']//div[@role='tab'][.//span[normalize-space()='Following']]",
        "xpath=//nav[@aria-live='polite']//div[@role='tab'][.//span[normalize-space()='Following']]",
        "xpath=//div[@role='tablist']//div[@role='tab'][.//span[normalize-space()='Following']]",
    ]

    todos_nuevos = []
    browser = None
    context = None
    page = None

    try:
        async with Stealth().use_async(async_playwright()) as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
            await context.add_cookies(cookies)
            page = await context.new_page()

            logger.info("Navegando a /home para scraping de feed...")
            await page.goto("https://x.com/home", timeout=60000)

            if any(x in page.url for x in ["login", "unsupported-browser", "consent", "challenge", "error"]):
                logger.error(f"⚠️ Bloqueo detectado al navegar a /home (url: {page.url})")
                return []

            await page.wait_for_selector("[data-testid='tweet']", timeout=30000, state="visible")
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Intentar click en pestaña Following
            # X requiere el doble click con pausa: click → 3s → click → 3s → scraping
            tab_clicked = False
            for xpath in FOLLOWING_TAB_XPATHS:
                try:
                    tab = await page.query_selector(xpath)
                    if tab:
                        logger.info(f"Click #1 en 'Following' con selector: {xpath}")
                        await tab.click()
                        await asyncio.sleep(3.0)

                        # Segundo click en el mismo selector (re-query para evitar stale element)
                        tab = await page.query_selector(xpath)
                        if tab:
                            logger.info("Click #2 en 'Following'")
                            await tab.click()
                            await asyncio.sleep(3.0)

                        await page.wait_for_selector("[data-testid='tweet']", timeout=15000, state="visible")
                        tab_clicked = True
                        break
                except Exception as e:
                    logger.warning(f"Selector '{xpath}' falló: {e}")

            if not tab_clicked:
                logger.warning("No se encontró la pestaña 'Following'. Usando el feed activo por defecto.")

            # Scroll + extracción
            tweets = []
            tweet_ids = set()
            idle_scrolls = 0

            while len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls:
                tweet_elements = await page.query_selector_all("[data-testid='tweet']")
                new_found = False

                for tweet in tweet_elements:
                    try:
                        link_el = await tweet.query_selector('a[href*="/status/"]')
                        content_el = await tweet.query_selector("[data-testid='tweetText']")
                        time_el = await tweet.query_selector("time")

                        if not (link_el and content_el and time_el):
                            continue

                        link = await link_el.get_attribute('href')
                        tweet_id = link.split("/")[-1]

                        if tweet_id in tweet_ids:
                            continue

                        social_context = await tweet.query_selector('span[data-testid="socialContext"]')
                        is_retweet = False
                        if social_context:
                            text = (await social_context.inner_text()).lower()
                            if "reposteó" in text or "retweeted" in text:
                                is_retweet = True

                        has_image = bool(await tweet.query_selector('img[src*="twimg.com/media/"]'))

                        tweet_data = {
                            "content": await get_full_tweet_text(tweet, f"https://x.com{link}", context),
                            "date": await time_el.get_attribute("datetime"),
                            "url": f"https://x.com{link}",
                            "is_retweet": is_retweet,
                            "has_image": has_image
                        }

                        if not tweet_data["content"] or not tweet_data["date"] or not tweet_data["url"]:
                            continue

                        tweets.append(tweet_data)
                        tweet_ids.add(tweet_id)
                        new_found = True

                        if len(tweets) >= max_tweets:
                            break
                    except Exception as e:
                        logger.error(f"Error extrayendo tweet del feed: {e}")
                        continue

                if not new_found:
                    idle_scrolls += 1
                else:
                    idle_scrolls = 0

                if len(tweets) < max_tweets and idle_scrolls < max_idle_scrolls:
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    pause = random.uniform(1.2, 2.5) if MODO_HUMANO else random.uniform(0.8, 1.5)
                    await asyncio.sleep(pause)

            logger.info(f"Feed scrapeado: {len(tweets)} tweets extraídos en total.")
            # "__feed__" como user para que DynamoDB indexe por modo; el user_handle real
            # queda en el Parquet vía URL_PATTERN igual que siempre.
            nuevos = save_tweets_to_db(tweets, "__feed__")
            logger.info(f"{len(nuevos)} tweets nuevos del feed guardados.")
            todos_nuevos.extend(nuevos)

            if todos_nuevos:
                upload_to_s3(todos_nuevos)

            return todos_nuevos

    except Exception as e:
        logger.error(f"Error general en async_scrape_feed_with_stealth: {e}")
        return []
    finally:
        try:
            if page: await page.close()
            if context: await context.close()
            if browser: await browser.close()
        except Exception as e:
            logger.warning(f"Error cerrando browser/context en feed: {e}")


# Ejemplo de uso
if __name__ == "__main__":
    # Ejecutar solo una vez para guardar cookies
    login_and_save_cookies()
    exit(0)
