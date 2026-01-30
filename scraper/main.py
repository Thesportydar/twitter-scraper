import os
import json
import asyncio
import boto3
import logging
from scraper import async_scrape_multiple_users_with_stealth

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

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
    """Configura el entorno obteniendo cookies y configs de SSM."""
    
    cookies = []
    user_configs = []

    # 1. Obtener Cookies
    cookies_param = os.getenv("SSM_COOKIES_PARAM", "/twitter-scraper/cookies")
    try:
        cookies_json = get_ssm_parameter(cookies_param)
        cookies = json.loads(cookies_json)
        logger.info(f"Cookies cargadas desde SSM: {cookies_param}")
    except Exception as e:
        logger.error(f"No se pudieron cargar las cookies. El scraper probablemente fallará. Error: {e}")

    # 2. Obtener User Configs
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
        # Configurar entorno (SSM)
        cookies, user_configs = setup_environment()
        
        # Ejecutar scraping
        if user_configs:
            # Ajustar parámetros por defecto si no vienen en el JSON
            for cfg in user_configs:
                if "max_idle_scrolls" not in cfg:
                    cfg["max_idle_scrolls"] = 2
                if "modo_humano" not in cfg:
                    cfg["modo_humano"] = True

            logger.info("Iniciando scraping asíncrono...")
            nuevos_tweets = await async_scrape_multiple_users_with_stealth(user_configs, cookies)
            logger.info(f"Ejecución finalizada. Total tweets nuevos: {len(nuevos_tweets)}")
        else:
            logger.warning("No se encontraron configuraciones de usuarios para procesar.")
            
    except Exception as e:
        logger.critical(f"Error crítico en la ejecución principal: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
