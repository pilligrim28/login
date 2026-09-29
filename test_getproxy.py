#!/usr/bin/env python3
"""
Тестовый скрипт для проверки getproxy.pro интеграции.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.config import Config
from core.proxy_manager import ProxyManager


def test_proxy_manager():
    """Тест ProxyManager с getproxy.pro."""
    print('\n=== Test ProxyManager with getproxy.pro ===')
    
    config = Config('.env')
    print(f'Proxy enabled: {config.get("proxy.enabled")}')
    print(f'Proxy mode: {config.get("proxy.mode")}')
    print(f'Getproxy API key: {config.get("proxy.getproxy_api_key") or "(not set)"}')
    
    pm = ProxyManager(config)
    print(f'Proxies loaded: {len(pm.proxies)}')
    
    if pm.proxies:
        proxy = pm.get_next()
        print(f'Next proxy: {proxy}')
    else:
        print('No proxies loaded (API key not set)')
    
    return pm


async def test_proxy_with_browser(proxy_config):
    """Тест прокси с браузером."""
    print('\n=== Test proxy with browser ===')
    
    if not proxy_config:
        print('No proxy config to test')
        return False
    
    from camoufox.async_api import AsyncCamoufox
    
    try:
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
        print(f'✓ httpbin.org: {page.url}')
        
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


async def main():
    print('=' * 60)
    print('Testing getproxy.pro integration')
    print('=' * 60)
    
    # Test 1: ProxyManager
    pm = test_proxy_manager()
    
    # Test 2: Browser test
    proxy = pm.get_next() if pm.proxies else None
    if proxy:
        # Форматируем прокси для Camoufox
        proxy_config = {'server': f"http://{proxy['server']}"}
        if proxy.get('username') and proxy.get('password'):
            proxy_config['username'] = proxy['username']
            proxy_config['password'] = proxy['password']
        
        await test_proxy_with_browser(proxy_config)
    else:
        print('\nSkipping browser test (no proxy)')
    
    print('\n' + '=' * 60)
    print('Test complete')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
