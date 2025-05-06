import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import time
import pickle
import os
import logging
import asyncio
import random
import pandas as pd
from datetime import datetime
from openpyxl import load_workbook
from telegram.error import BadRequest

# Настройки логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ozon_bot.log'),  # Логи в файл
        logging.StreamHandler()  # Логи в консоль
    ]
)

COOKIES_FILE = "ozon_cookies.pkl"
CHECK_INTERVAL = 10  # Проверять каждые 10 секунд
TIMEOUT = 40  # Максимальное время ожидания (120 сек)
BRAND_URL = "https://uz.ozon.com/brand/naturalino-100091998"

# Инициализация драйвера
def init_driver(headless=True):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)
    return driver

# Проверка авторизации
def check_login(driver):
    try:
        driver.get("https://uz.ozon.com")
        time.sleep(1)
        
        auth_indicators = [
            "Мой профиль", "Кабинет", "Избранное", 
            "Мои заказы", "Выйти"
        ]
        page_text = driver.page_source
        
        with open('./page.html', 'w', encoding='utf-8') as f:
            f.write(page_text)
            
        return any(indicator in page_text for indicator in auth_indicators)
    except Exception as e:
        logging.error(f"Ошибка проверки авторизации: {e}")
        return False

# Сохранение куков
def save_cookies(driver):
    try:
        current_domain = driver.current_url.split('/')[2]
        driver.get(f"https://{current_domain}")
        time.sleep(1)
        
        cookies = driver.get_cookies()
        with open(COOKIES_FILE, "wb") as f:
            pickle.dump((current_domain, cookies), f)
        return True
    except Exception as e:
        logging.error(f"Ошибка сохранения куков: {e}")
        return False

# Загрузка куков
def load_cookies(driver):
    if not os.path.exists(COOKIES_FILE):
        return False
        
    try:
        with open(COOKIES_FILE, "rb") as f:
            domain, cookies = pickle.load(f)
        
        driver.get(f"https://{domain}")
        time.sleep(1)
        
        driver.delete_all_cookies()
        
        for cookie in cookies:
            driver.add_cookie(cookie)
        
        driver.refresh()
        time.sleep(1)
        return check_login(driver)
    except Exception as e:
        logging.error(f"Ошибка загрузки куков: {e}")
        return False

# Проверка ограничения доступа
def check_access_restricted(driver):
    try:
        page_text = driver.page_source
        return "Доступ ограничен" in page_text or "Access restricted" in page_text
    except Exception as e:
        logging.error(f"Ошибка проверки ограничения доступа: {e}")
        return False

# Парсинг товаров бренда
def parse_brand_products(driver, url):
    wait = WebDriverWait(driver, 10)
    driver.get(url)
    time.sleep(random.uniform(2, 4))
    
    if check_access_restricted(driver):
        logging.error("Доступ ограничен")
        return None
    
    products = []
    
    while True:
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(random.uniform(0.5, 1.5))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(2, 4))

        try:
            items = wait.until(EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class, 'tile-root')]")))
            for item in items:
                try:
                    name = item.find_element(By.XPATH, ".//span[contains(@class, 'tsBody500Medium')]").text
                    
                    price = "N/A"
                    try:
                        price_elem = item.find_element(By.XPATH, ".//span[contains(@class, 'tsHeadline500Medium')]")
                        price = price_elem.text
                    except:
                        pass
                    
                    link = item.find_element(By.XPATH, ".//a[contains(@class, 'tile-clickable-element')]").get_attribute("href")
                    sku = link.split("-")[-1].split("/")[0] if "-" in link else "N/A"
                    
                    products.append({
                        "Name": name,
                        "SKU": sku,
                        "Price (Ozon Card)": price
                    })
                except Exception as e:
                    logging.error(f"Ошибка парсинга товара: {e}")
        except Exception as e:
            logging.error(f"Ошибка загрузки товаров: {e}")
            break

        try:
            next_button = driver.find_element(By.XPATH, "//a[contains(@class, 'next-page')]")
            if "disabled" in next_button.get_attribute("class"):
                break
            next_button.click()
            time.sleep(random.uniform(2, 4))
        except:
            break

    return products

async def send_reply(update: Update, text: str):
    """Helper function to send a reply based on whether update is a message or callback query."""
    try:
        if update.message:
            await update.message.reply_text(text)
        elif update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(text)
        else:
            logging.error("Не удалось отправить сообщение: отсутствует message или callback_query.message")
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

async def check_auth_task(update: Update, driver):
    start_time = time.time()
    logged_in = False
    
    while time.time() - start_time < TIMEOUT:
        try:
            if check_login(driver):
                if save_cookies(driver):
                    await send_reply(update, "✅ Вы успешно авторизованы! Куки сохранены. Теперь вы можете использовать команду /parse или кнопку 'Парсить'.")
                else:
                    await send_reply(update, "✅ Вы авторизованы, но куки не сохранились. Теперь вы можете использовать команду /parse или кнопку 'Парсить'.")
                logged_in = True
                break
        except Exception as e:
            logging.error(f"Ошибка проверки: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)
    
    if not logged_in:
        await send_reply(update, "❌ Вы не вошли в систему. Попробуйте снова.")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    callback_data = query.data

    logging.info(f"Обработка callback: {callback_data}")

    if callback_data == "open_ozon":
        try:
            await query.message.reply_text(
                "🔑 Перейдите по ссылке и войдите в Ozon:\n"
                "👉 https://uz.ozon.com\n\n"
                "⏳ Проверяю авторизацию..."
            )
        except BadRequest as e:
            logging.error(f"Ошибка отправки сообщения авторизации: {e}")
            await query.message.reply_text("❌ Ошибка. Пожалуйста, попробуйте снова.")
            return

        driver = init_driver(headless=True)
        try:
            await check_auth_task(update, driver)
        finally:
            try:
                driver.quit()
            except:
                pass
    elif callback_data == "parse":
        await parse_command(update, context)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сообщение о проверке сессии
    try:
        checking_msg = await update.message.reply_text("⏳ Проверяем сессию...")
    except BadRequest as e:
        logging.error(f"Ошибка отправки сообщения проверки сессии: {e}")
        await update.message.reply_text("⏳ Проверяем сессию...")
        return

    # Проверяем существующую сессию
    driver = init_driver(headless=True)
    is_authorized = False
    try:
        if load_cookies(driver):
            is_authorized = True
    except Exception as e:
        logging.error(f"Ошибка проверки сессии при старте: {e}")
    finally:
        try:
            driver.quit()
        except:
            pass

    # Формируем инлайн-клавиатуру в зависимости от статуса авторизации
    keyboard_buttons = [[InlineKeyboardButton("🔍 Открыть Ozon", callback_data="open_ozon")]]
    if is_authorized:
        keyboard_buttons.append([InlineKeyboardButton("🔄 Парсить", callback_data="parse")])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    # Сообщение в зависимости от статуса авторизации
    try:
        if is_authorized:
            await checking_msg.edit_text(
                "✅ Вы уже авторизованы! Используйте команду /parse или кнопку 'Парсить' для парсинга товаров.",
                reply_markup=keyboard
            )
        else:
            await checking_msg.edit_text(
                "👋 Нажмите кнопку, чтобы авторизоваться в Ozon.",
                reply_markup=keyboard
            )
        logging.info("Инлайн-клавиатура успешно отправлена")
    except BadRequest as e:
        logging.error(f"Ошибка отправки инлайн-клавиатуры: {e}")
        # Fallback без клавиатуры
        if is_authorized:
            await checking_msg.edit_text(
                "✅ Вы уже авторизованы! Используйте команду /parse для парсинга товаров."
            )
        else:
            await checking_msg.edit_text(
                "👋 Пожалуйста, авторизуйтесь в Ozon. Используйте команду /start и следуйте инструкциям."
            )

async def parse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем наличие сессии
    if not os.path.exists(COOKIES_FILE):
        await send_reply(update, "❌ Сессия не найдена. Пожалуйста, сначала авторизуйтесь с помощью команды /start и кнопки 'Открыть Ozon'.")
        return

    await send_reply(update, "⏳ Начинаю парсинг товаров бренда Naturalino...")

    driver = init_driver(headless=True)
    try:
        # Загружаем куки
        if not load_cookies(driver):
            await send_reply(update, "❌ Не удалось загрузить сессию. Пожалуйста, авторизуйтесь заново.")
            return

        # Парсим товары
        products = parse_brand_products(driver, BRAND_URL)
        if not products:
            await send_reply(update, "❌ Не удалось получить товары. Возможно, доступ ограничен или произошла ошибка.")
            return

        # Создаем Excel-файл
        df = pd.DataFrame(products)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_file = f"naturalino_products_{timestamp}.xlsx"
        df.to_excel(excel_file, index=False)

        # Устанавливаем ширину столбцов
        wb = load_workbook(excel_file)
        ws = wb.active
        for col in ws.columns:
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = 75
        wb.save(excel_file)

        # Отправляем файл пользователю
        with open(excel_file, 'rb') as f:
            if update.message:
                await update.message.reply_document(document=f, caption="✅ Парсинг завершен! Вот список товаров бренда Naturalino.")
            elif update.callback_query and update.callback_query.message:
                await update.callback_query.message.reply_document(document=f, caption="✅ Парсинг завершен! Вот список товаров бренда Naturalino.")

        # Удаляем временный файл
        os.remove(excel_file)

    except Exception as e:
        logging.error(f"Ошибка при парсинге: {e}")
        await send_reply(update, f"❌ Произошла ошибка при парсинге: {str(e)}")
    finally:
        try:
            driver.quit()
        except:
            pass

def main():
    app = Application.builder().token("7547668298:AAFhrpD9gQROtrqLfo_UIeyYEXyC31fyWSI").build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("parse", parse_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    print("🤖 Бот запущен!")
    logging.info("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()