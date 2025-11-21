from playwright.sync_api import sync_playwright
import json
import os
import time
import random
import boto3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timedelta
import logging
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import collections


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

MAX_TWEETS = int(os.getenv("MAX_TWEETS", 15))
MAX_IDLE_SCROLLS = int(os.getenv("MAX_IDLE_SCROLLS", 2))
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")
MODO_HUMANO = os.getenv("MODO_HUMANO", "true").lower() in ("1", "true", "yes")
# COOKIES_FILE removed
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "Tweet")

def init_db():
    """Inicializa la tabla de DynamoDB si no existe."""
    dynamodb = boto3.resource('dynamodb')
    try:
        table = dynamodb.create_table(
            TableName=DYNAMODB_TABLE,
            KeySchema=[{'AttributeName': 'Id', 'KeyType': 'HASH'}],
            AttributeDefinitions=[
                {'AttributeName': 'Id', 'AttributeType': 'S'},
                {'AttributeName': 'User', 'AttributeType': 'S'},
                {'AttributeName': 'ScrapedAt', 'AttributeType': 'S'}
            ],
            GlobalSecondaryIndexes=[{
                'IndexName': 'UserIndex',
                'KeySchema': [
                    {'AttributeName': 'User', 'KeyType': 'HASH'},
                    {'AttributeName': 'ScrapedAt', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'}
            }],
            BillingMode='PAY_PER_REQUEST'
        )
        print(f"Creando tabla {DYNAMODB_TABLE}...")
        table.wait_until_exists()
        
        # Habilitar TTL
        client = boto3.client('dynamodb')
        client.update_time_to_live(
            TableName=DYNAMODB_TABLE,
            TimeToLiveSpecification={
                'Enabled': True,
                'AttributeName': 'ExpireAt'
            }
        )
        print(f"Tabla {DYNAMODB_TABLE} creada con TTL.")
    except Exception as e:
        if "ResourceInUseException" in str(e):
            pass
        else:
            logger.error(f"Error inicializando DynamoDB: {e}")

def send_cloudwatch_metrics(metrics):
    """Envía métricas a CloudWatch para monitoreo."""
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

def save_tweets_to_db(tweets, user):
    """Guarda los tweets en DynamoDB con batch insert y TTL de 72hs."""
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(DYNAMODB_TABLE)
    
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
    
    # Batch get para verificar existencia (limitado a 100 items por request, aquí asumimos <100)
    if ids_to_check:
        try:
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
    try:
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

def get_tweets_from_db():
    """Devuelve todos los tweets almacenados en DynamoDB."""
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

def clear_tweets_in_db():
    """Elimina todos los tweets de la tabla (recreándola)."""
    dynamodb = boto3.resource('dynamodb')
    try:
        table = dynamodb.Table(DYNAMODB_TABLE)
        table.delete()
        table.wait_until_not_exists()
        init_db()
    except Exception as e:
        logger.error(f"Error limpiando DB: {e}")

def get_latest_tweet_ids_from_db(username, limit=20):
    """Obtiene los IDs de los últimos tweets de un usuario en DynamoDB."""
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
                                    "content": await content_el.inner_text(),
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
                                if modo_humano or random.random() < 0.3:
                                    await asyncio.sleep(random.uniform(0.15, 0.5))
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
                            if modo_humano or random.random() < 0.2:
                                await asyncio.sleep(random.uniform(1.0, 2.0))
                            else:
                                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                                await asyncio.sleep(random.uniform(1.5, 3.0))
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
