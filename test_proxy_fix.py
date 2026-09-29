#!/usr/bin/env python3
"""
Тестовый скрипт для проверки исправления прокси.
Проверяет:
1. Camoufox с прокси (разные форматы)
2. Camoufox без прокси
3. Chromium с прокси
4. Chromium без прокси
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import async_playwright


PROXY = {
    'server': '92.204.171.83:9000',
    'type': 'http',
    'username': 'a995a71bbb0ee8097afe633a914168e5-type-residential-country-CR',
    'password': '59c8d77e-4957-4af2-9058-3cac156a4e2e'
}


def format_proxy(proxy):
    """Форматируем прокси как в исправленном коде."""
    ptype = (proxy.get('type') or 'http').lower()
    server = proxy['server']
    if ptype.startswith('socks'):
        server = f'{ptype}://{server}'
    else:
        server = f'http://{server}'
    
    proxy_config = {'server': server}
    if proxy.get('username'):
        proxy_config['username'] = proxy['username']
        proxy_config['password'] = proxy.get('password', '')
    
    return proxy_config


async def test_camoufox_with_proxy():
    """Тест Camoufox с прокси."""
    print('\n=== Test 1: Camoufox с прокси ===')
    proxy_config = format_proxy(PROXY)
    print(f'Proxy config: {proxy_config}')
    
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
        
        await browser.close()
        await cf.__aexit__(None, None, None)
        return True
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:100]}')
        return False


async def test_camoufox_without_proxy():
    """Тест Camoufox без прокси."""
    print('\n=== Test 2: Camoufox без прокси ===')
    
    try:
        cf = AsyncCamoufox(
            headless=True,
            geoip=True,
            humanize=True
        )
        browser = await cf.__aenter__()
        context = await browser.new_context()
        page = await context.new_page()
        
        # Тест: signup.live.com
        await page.goto('https://signup.live.com/signup', wait_until='domcontentloaded', timeout=45000)
        print(f'✓ signup.live.com: {page.url}')
        
        title = await page.title()
        print(f'✓ Title: {title}')
        
        await browser.close()
        await cf.__aexit__(None, None, None)
        return True
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:100]}')
        return False


async def test_chromium_with_proxy():
    """Тест Chromium с прокси."""
    print('\n=== Test 3: Chromium с прокси ===')
    proxy_config = format_proxy(PROXY)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto('https://httpbin.org/ip', wait_until='domcontentloaded', timeout=30000)
            print(f'✓ httpbin.org: {page.url}')
            
            await browser.close()
        return True
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:100]}')
        return False


async def test_chromium_without_proxy():
    """Тест Chromium без прокси."""
    print('\n=== Test 4: Chromium без прокси ===')
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto('https://signup.live.com/signup', wait_until='domcontentloaded', timeout=45000)
            print(f'✓ signup.live.com: {page.url}')
            
            title = await page.title()
            print(f'✓ Title: {title}')
            
            await browser.close()
        return True
    except Exception as e:
        print(f'✗ FAILED: {str(e)[:100]}')
        return False


async def main():
    print('=' * 60)
    print('Testing proxy fix for registration')
    print('=' * 60)
    
    results = []
    
    # Test 1
    results.append(await test_camoufox_with_proxy())
    
    # Test 2
    results.append(await test_camoufox_without_proxy())
    
    # Test 3
    results.append(await test_chromium_with_proxy())
    
    # Test 4
    results.append(await test_chromium_without_proxy())
    
    print('\n' + '=' * 60)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    print('=' * 60)
    
    return all(results)


if __name__ == '__main__':
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
