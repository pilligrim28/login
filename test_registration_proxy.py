#!/usr/bin/env python3
"""
Скрипт для тестирования регистрации с прокси.
Использует прокси от getproxy.pro или отключает прокси.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import async_playwright


# ============================================
# КОНФИГУРАЦИЯ
# ============================================

# Вариант 1: Использовать getproxy.pro
USE_GETPROXY = True
GETPROXY_API_KEY = ""  # <-- Вставьте ваш API ключ от getproxy.pro
GETPROXY_COUNTRY = "all"  # или "US", "GB", "DE" и т.д.

# Вариант 2: Использовать статические прокси
USE_STATIC_PROXY = False
STATIC_PROXIES = [
    # "host:port:username:password",
    # "host:port:username:password",
]

# Вариант 3: Без прокси
USE_NO_PROXY = False


async def test_with_getproxy():
    """Тест с getproxy.pro."""
    print('\n=== Test with getproxy.pro ===')
    
    if not GETPROXY_API_KEY:
        print('⚠️ API ключ не настроен')
        return False
    
    # Получаем прокси от getproxy.pro
    import httpx
    url = "https://getproxy.pro/api/v1/proxy"
    headers = {"Authorization": f"Bearer {GETPROXY_API_KEY}"}
    params = {"country": GETPROXY_COUNTRY, "length": 1}
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "success" or "proxies" not in data:
                print(f'⚠️ Ошибка получения прокси: {data}')
                return False
            
            proxy_str = data["proxies"][0]
            print(f'Получен прокси: {proxy_str}')
            
            # Парсим прокси
            parts = proxy_str.split(":")
            server = f"{parts[0]}:{parts[1]}"
            username = parts[2] if len(parts) > 2 else None
            password = parts[3] if len(parts) > 3 else None
            
            # Форматируем для Camoufox
            proxy_config = {'server': f'http://{server}'}
            if username and password:
                proxy_config['username'] = username
                proxy_config['password'] = password
            
            # Тест с браузером
            cf = AsyncCamoufox(
                headless=True,
                geoip=True,
                humanize=True,
                proxy=proxy_config
            )
            
            browser = await cf.__aenter__()
            context = await browser.new_context()
            page = await context.new_page()
            
            # Тест 1: httpbin.org
            await page.goto('https://httpbin.org/ip', wait_until='domcontentloaded', timeout=30000)
            content = await page.content()
            print(f'✓ httpbin.org: {content[:100]}')
            
            # Тест 2: signup.live.com
            await page.goto('https://signup.live.com/signup', wait_until='domcontentloaded', timeout=45000)
            print(f'✓ signup.live.com: {page.url}')
            
            title = await page.title()
            print(f'✓ Title: {title}')
            
            await browser.close()
            await cf.__aexit__(None, None, None)
            return True
            
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:200]}')
        return False


async def test_with_static_proxy():
    """Тест со статическими прокси."""
    print('\n=== Test with static proxy ===')
    
    if not STATIC_PROXIES:
        print('⚠️ Прокси не настроены')
        return False
    
    proxy_str = STATIC_PROXIES[0]
    print(f'Используем прокси: {proxy_str}')
    
    parts = proxy_str.split(":")
    server = f"{parts[0]}:{parts[1]}"
    username = parts[2] if len(parts) > 2 else None
    password = parts[3] if len(parts) > 3 else None
    
    proxy_config = {'server': f'http://{server}'}
    if username and password:
        proxy_config['username'] = username
        proxy_config['password'] = password
    
    cf = AsyncCamoufox(
        headless=True,
        geoip=True,
        humanize=True,
        proxy=proxy_config
    )
    
    try:
        browser = await cf.__aenter__()
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto('https://signup.live.com/signup', wait_until='domcontentloaded', timeout=45000)
        print(f'✓ signup.live.com: {page.url}')
        
        title = await page.title()
        print(f'✓ Title: {title}')
        
        await browser.close()
        await cf.__aexit__(None, None, None)
        return True
        
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:200]}')
        return False


async def test_without_proxy():
    """Тест без прокси."""
    print('\n=== Test without proxy ===')
    
    cf = AsyncCamoufox(
        headless=True,
        geoip=True,
        humanize=True
    )
    
    try:
        browser = await cf.__aenter__()
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto('https://signup.live.com/signup', wait_until='domcontentloaded', timeout=45000)
        print(f'✓ signup.live.com: {page.url}')
        
        title = await page.title()
        print(f'✓ Title: {title}')
        
        await browser.close()
        await cf.__aexit__(None, None, None)
        return True
        
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:200]}')
        return False


async def main():
    print('=' * 60)
    print('Testing registration with proxy')
    print('=' * 60)
    
    if USE_GETPROXY:
        success = await test_with_getproxy()
    elif USE_STATIC_PROXY:
        success = await test_with_static_proxy()
    elif USE_NO_PROXY:
        success = await test_without_proxy()
    else:
        print('⚠️ Не выбран режим прокси')
        return
    
    print('\n' + '=' * 60)
    if success:
        print('✅ Все тесты пройдены')
    else:
        print('❌ Тесты не пройдены')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
