import os
import json
import asyncio
import boto3
import logging
from scraper import async_scrape_multiple_users_with_stealth, async_scrape_feed_with_stealth

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

LOCAL_TEST = os.getenv("LOCAL_TEST", "false").lower() in ("true", "1", "yes")

def get_ssm_parameter(param_name):
    """Obtiene un parámetro de SSM Parameter Store."""
    ssm = boto3.client('ssm')
    try:
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        logger.error(f"Error obteniendo parámetro {param_name} de SSM: {e}")
        raise

def setup_environment():
    """Configura el entorno obteniendo cookies y configs de SSM (o localmente si LOCAL_TEST es True)."""
    
    cookies = []
    user_configs = []

    if LOCAL_TEST:
        logger.info("[LOCAL TEST] Configurando entorno local (sin SSM)...")
        
        # 1. Cargar Cookies
        cookies_file = "cookies.json"
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file, "r") as f:
                    cookies = json.load(f)
                logger.info(f"[LOCAL TEST] Cookies cargadas desde archivo local: {cookies_file}")
            except Exception as e:
                logger.error(f"[LOCAL TEST] Error leyendo cookies locales: {e}")
        else:
            logger.warning(f"[LOCAL TEST] Archivo '{cookies_file}' no encontrado. Playwright podría fallar si se requiere sesión.")

        # 2. Cargar User Configs
        config_file = "user_configs.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    user_configs = json.load(f)
                logger.info(f"[LOCAL TEST] Configuración de usuarios cargada desde: {config_file} ({len(user_configs)} usuarios)")
            except Exception as e:
                logger.error(f"[LOCAL TEST] Error leyendo {config_file}: {e}")
                raise
        else:
            logger.info("[LOCAL TEST] 'user_configs.json' no encontrado. Usando config mock por defecto (@SalvaDiStefano).")
            user_configs = [
                {
                    "username": "SalvaDiStefano",
                    "max_tweets": 2,
                    "max_idle_scrolls": 2,
                    "modo_humano": True
                }
            ]

        return cookies, user_configs

    # 1. Obtener Cookies desde SSM
    cookies_param = os.getenv("SSM_COOKIES_PARAM", "/twitter-scraper/cookies")
    try:
        cookies_json = get_ssm_parameter(cookies_param)
        cookies = json.loads(cookies_json)
        logger.info(f"Cookies cargadas desde SSM: {cookies_param}")
    except Exception as e:
        logger.error(f"No se pudieron cargar las cookies. El scraper probablemente fallará. Error: {e}")

    # 2. Obtener User Configs desde SSM
    config_param = os.getenv("SSM_CONFIG_PARAM", "/twitter-scraper/user-configs")
    try:
        config_json = get_ssm_parameter(config_param)
        user_configs = json.loads(config_json)
        logger.info(f"Configuración de usuarios cargada desde SSM: {config_param} ({len(user_configs)} usuarios)")
    except Exception as e:
        logger.error(f"Error cargando configuración de usuarios: {e}")
        raise

    return cookies, user_configs

async def main():
    logger.info("Iniciando ejecución del scraper...")
    
    try:
        cookies, all_configs = setup_environment()
        
        # Separar configs de feed de configs de usuarios
        feed_configs  = [c for c in all_configs if c.get("mode") == "feed"]
        user_configs  = [c for c in all_configs if c.get("mode") != "feed"]

        total_nuevos = 0

        # --- Modo feed ---
        for cfg in feed_configs:
            max_tweets      = int(cfg.get("max_tweets", 100))
            max_idle_scrolls = int(cfg.get("max_idle_scrolls", 5))
            logger.info(f"Iniciando scraping de feed (max_tweets={max_tweets}, max_idle_scrolls={max_idle_scrolls})...")
            nuevos = await async_scrape_feed_with_stealth(
                cookies,
                max_tweets=max_tweets,
                max_idle_scrolls=max_idle_scrolls,
            )
            logger.info(f"Feed finalizado. Tweets nuevos: {len(nuevos)}")
            total_nuevos += len(nuevos)

        # --- Modo usuarios ---
        if user_configs:
            # Defaults para campos opcionales
            for cfg in user_configs:
                cfg.setdefault("max_idle_scrolls", 2)
                cfg.setdefault("modo_humano", True)

            logger.info(f"Iniciando scraping de {len(user_configs)} usuario(s)...")
            nuevos = await async_scrape_multiple_users_with_stealth(user_configs, cookies)
            logger.info(f"Scraping de usuarios finalizado. Tweets nuevos: {len(nuevos)}")
            total_nuevos += len(nuevos)

        if not feed_configs and not user_configs:
            logger.warning("No se encontraron configuraciones para procesar.")

        logger.info(f"Ejecución finalizada. Total tweets nuevos: {total_nuevos}")
            
    except Exception as e:
        logger.critical(f"Error crítico en la ejecución principal: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
