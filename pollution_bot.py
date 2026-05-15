import json
import os
import requests
from playwright.sync_api import sync_playwright

# --- НАСТРОЙКИ ---
STATE_FILE = 'pollution_state.json'
# Замените эти данные на реальные токен и ID канала
BOT_TOKEN = '123456789:ABCDEF...' 
CHANNEL_ID = '-1001234567890'

COLOR_TO_LEVEL = {
    'green': 1,
    'yellow': 2,
    'orange': 3,
    'red': 4
}

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": text}
    try:
        # Для тестов не шлем реальный запрос, если токен не настроен
        if "123456789:ABCDEF" not in BOT_TOKEN:
            requests.post(url, json=payload)
        print(f"✅ Отправлено уведомление: {text}")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

def get_current_pollution_level():
    """Открывает сайт через Playwright и парсит уровень загрязнения Никосии"""
    print("Подключение к сайту качества воздуха...")
    with sync_playwright() as p:
        # headless=True значит браузер работает невидимо, без графического интерфейса
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.airquality.dli.mlsi.gov.cy/", timeout=60000)
        
        # Ждем загрузки карты и маркеров
        page.wait_for_selector("#image_1066", timeout=15000)
        
        # Получаем атрибут xlink:href у элемента Nicosia (image_1066)
        # Пример: ../../../sites/default/files/yellow-double.png
        href = page.locator("#image_1066").get_attribute("xlink:href")
        browser.close()

        if not href:
            return None
            
        print(f"Получен маркер: {href}")
        for color, level in COLOR_TO_LEVEL.items():
            if color in href:
                return level
    return None

def main():
    current_level = get_current_pollution_level()
    
    if not current_level:
        print("❌ Не удалось получить текущий уровень.")
        return

    print(f"Текущий уровень Никосии: {current_level}")
    
    # Загружаем предыдущий уровень
    old_level = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                state = json.load(f)
                old_level = state.get('nicosia_level')
            except json.JSONDecodeError:
                pass

    if current_level != old_level:
        print(f"Уровень изменился: {old_level} -> {current_level}")
        
        # Сохраняем новый стейт
        with open(STATE_FILE, 'w') as f:
            json.dump({'nicosia_level': current_level}, f)
            
        # Логика Умных Уведомлений
        should_notify = True
        
        if old_level is not None:
            # Игнорируем скачки между 1 и 2
            if (old_level == 1 and current_level == 2) or (old_level == 2 and current_level == 1):
                should_notify = False
                print("ℹ️ Изменение между 1 и 2. Уведомление проигнорировано (окна можно не закрывать).")

        if should_notify:
            send_telegram_message(f"Текущий уровень: {current_level}")
    else:
        print("Уровень не изменился. Ждем.")

if __name__ == '__main__':
    main()
