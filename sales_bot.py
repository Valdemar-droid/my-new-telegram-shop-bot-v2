import os
import logging
import sqlite3
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Получение переменных окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0")) # Default to 0 if not set

# Проверка, установлены ли все необходимые переменные
if not TELEGRAM_BOT_TOKEN:
    logger.error("Ошибка: Переменная окружения TELEGRAM_BOT_TOKEN не установлена. Бот не может быть запущен.")
    exit(1) # Завершаем выполнение, если токен не найден

# Инициализация Google Gemini AI
try:
    if GOOGLE_API_KEY:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-pro")
        logger.info("Google Gemini AI model initialized successfully.")
    else:
        logger.warning("Переменная окружения GOOGLE_API_KEY не установлена. Функции ИИ будут недоступны.")
        model = None # Set model to None if API key is missing
except Exception as e:
    logger.error(f"Ошибка при инициализации Google Gemini AI: {e}")
    model = None

# --- Состояния для ConversationHandler ---
ASK_AI_QUESTION = 1

# --- Функции для работы с базой данных SQLite ---
DATABASE_NAME = 'bot_database.db'

def init_db():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                image_url TEXT
            )
        ''')
        # Проверка наличия данных и добавление при необходимости (для тестирования)
        cursor.execute('SELECT COUNT(*) FROM products')
        if cursor.fetchone()[0] == 0:
            logger.info("Добавление тестовых данных в базу данных products...")
            cursor.execute("INSERT INTO products (name, description, price, image_url) VALUES (?, ?, ?, ?)",
                           ('Ноутбук ProX', 'Мощный ноутбук для работы и игр.', 1200.00, 'https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Laptop_computer_on_table.jpg/640px-Laptop_computer_on_table.jpg'))
            cursor.execute("INSERT INTO products (name, description, price, image_url) VALUES (?, ?, ?, ?)",
                           ('Смартфон Ultra', 'Флагманский смартфон с лучшей камерой.', 800.00, 'https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/IPhone_14_Pro_Max_mockup.png/640px-IPhone_14_Pro_Max_mockup.png'))
            conn.commit()
            logger.info("Тестовые данные успешно добавлены.")
        conn.close()
        logger.info("База данных инициализирована.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")

def get_products():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT name, description, price, image_url FROM products")
        products = cursor.fetchall()
        conn.close()
        logger.info(f"Загружено {len(products)} товаров из базы данных.")
        return products
    except Exception as e:
        logger.error(f"Ошибка при получении товаров из БД: {e}")
        return []

# --- Функции для обработчиков команд ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"Пользователь {user.full_name} ({user.id}) начал диалог.")
    keyboard = [
        [
            InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
            InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Я бот-магазин. Выберите действие:",
        reply_markup=reply_markup,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Используйте команды: /start, /help.\n"
                                    "Или кнопки для взаимодействия.")

async def show_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer() # Отвечаем на callback, чтобы убрать "часики" с кнопки

    products = get_products()
    if products:
        response_text = "Вот что есть в нашем магазине:\n\n"
        for name, description, price, image_url in products:
            response_text += (
                f"<b>{name}</b>\n"
                f"Описание: {description}\n"
                f"Цена: ${price:.2f}\n"
            )
            if image_url:
                response_text += f"Изображение: {image_url}\n"
            response_text += "\n"
        await query.edit_message_text(text=response_text, parse_mode="HTML")
        # Возвращаем основные кнопки после показа товаров
        keyboard = [
            [
                InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
                InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите следующее действие:", reply_markup=reply_markup)
    else:
        await query.edit_message_text(text="В магазине пока нет товаров.")
        # Возвращаем основные кнопки после показа товаров
        keyboard = [
            [
                InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
                InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите следующее действие:", reply_markup=reply_markup)


# --- Функции для диалога с ИИ (ConversationHandler) ---

async def ask_ai_entry_point(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer() # Отвечаем на callback
        message_to_edit = query.message
    elif update.message: # Если команда пришла как текстовое сообщение (хотя ожидается кнопка)
        message_to_edit = update.message
    else:
        logger.warning("ask_ai_entry_point called without message or callback_query.")
        return ConversationHandler.END # Завершаем, если нет контекста

    if model is None:
        await message_to_edit.reply_text(
            "Извините, функция ИИ сейчас недоступна. Пожалуйста, убедитесь, что GOOGLE_API_KEY установлен правильно."
        )
        return ConversationHandler.END # Завершаем диалог, если ИИ недоступен

    await message_to_edit.reply_text(
        "Я готов отвечать на ваши вопросы! Спросите меня о чем угодно. "
        "Чтобы закончить диалог с ИИ, введите /done"
    )
    # Возвращаем основные кнопки, если это был callback от кнопки
    if query:
        keyboard = [
            [
                InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
                InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите следующее действие:", reply_markup=reply_markup)


    return ASK_AI_QUESTION

async def handle_ai_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_question = update.message.text
    if not user_question:
        await update.message.reply_text("Пожалуйста, введите ваш вопрос текстом.")
        return ASK_AI_QUESTION

    logger.info(f"Получен вопрос для ИИ от {update.effective_user.full_name}: {user_question}")

    if model is None:
        await update.message.reply_text(
            "Извините, функция ИИ сейчас недоступна. Пожалуйста, убедитесь, что GOOGLE_API_KEY установлен правильно."
        )
        return ConversationHandler.END

    try:
        # Отправляем сообщение "Печатает..."
        await update.message.chat.send_action("typing")
        response = model.generate_content(user_question)
        ai_response = response.text
        logger.info(f"Ответ ИИ: {ai_response}")
        await update.message.reply_text(ai_response)
    except Exception as e:
        logger.error(f"Ошибка при обращении к Gemini AI: {e}")
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего запроса ИИ. Пожалуйста, попробуйте еще раз."
        )
    return ASK_AI_QUESTION # Остаемся в состоянии ожидания вопросов

async def done_ai_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Диалог с ИИ завершен. Чем еще могу помочь?",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
                                         InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai")]
                                    ]))
    return ConversationHandler.END

# --- Общий обработчик для неопознанных сообщений ---
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Неизвестная команда или сообщение от {update.effective_user.full_name}: {update.message.text}")
    await update.message.reply_text(
        "Извините, я не понял вашу команду. Используйте кнопки для взаимодействия.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Посмотреть товары", callback_data="show_products"),
             InlineKeyboardButton("Задать вопрос ИИ", callback_data="ask_ai")]
        ])
    )

def main() -> None:
    # Инициализация базы данных
    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Обработчик для кнопки "Посмотреть товары"
    application.add_handler(CallbackQueryHandler(show_products_callback, pattern="^show_products$"))

    # ConversationHandler для диалога с ИИ
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_ai_entry_point, pattern="^ask_ai$")],
        states={
            ASK_AI_QUESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_question),
                CommandHandler("done", done_ai_dialog),
            ],
        },
        fallbacks=[CommandHandler("done", done_ai_dialog)],
    )
    application.add_handler(conv_handler)

    # Обработчик для любых других сообщений, которые не были обработаны
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_command))

    # Запускаем бота
    logger.info("Бот запущен. Ожидание сообщений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()