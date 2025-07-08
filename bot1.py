import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler

# ===== НАСТРОЙКИ (теперь через переменные окружения) =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Получаем из Railway
SOURCE_GROUP_ID = int(os.environ.get("SOURCE_GROUP_ID", -1001234567890))  # Дефолтное значение (если не задано)
TARGET_GROUP_ID = int(os.environ.get("TARGET_GROUP_ID", -1002807172405))
TARGET_TOPIC_ID = int(os.environ.get("TARGET_TOPIC_ID")) if os.environ.get("73") else None
logging.basicConfig(
    filename='bot.log',  # Логи будут сохраняться в файл
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище тестов
test_sessions = {}  # {test_id: {'text': str, 'status': str, 'target_msg_id': int, 'user_data': dict}}

# ===== ТЕСТОВАЯ СИСТЕМА =====
async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс создания теста"""
    if update.effective_chat.id != SOURCE_GROUP_ID:
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Отправьте текст тестового задания:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_test")]])
    )
    return "AWAIT_TEST_TEXT"

async def handle_test_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает текст теста и отправляет его в рабочий чат"""
    test_id = update.message.message_id
    test_text = update.message.text
    
    # Отправляем тест в целевой чат с кнопкой
    keyboard = [[InlineKeyboardButton("✅ Я выполню", callback_data=f"do_test_{test_id}")]]
    sent_msg = await context.bot.send_message(
        chat_id=TARGET_GROUP_ID,
        text=f"🛑 ЗАДАНИЕ 🛑\n\n{test_text}",
        message_thread_id=TARGET_TOPIC_ID,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # Сохраняем информацию о тесте
    test_sessions[test_id] = {
        'text': test_text,
        'status': 'active',  # active / in_progress / completed
        'target_msg_id': sent_msg.message_id,
        'user_data': None
    }
    
    await update.message.reply_text("✅ Шаблон отправлен в рабочий чат!")
    return ConversationHandler.END

async def start_test_execution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатие кнопки 'Я выполню'"""
    query = update.callback_query
    await query.answer()
    
    test_id = int(query.data.split('_')[-1])
    if test_id not in test_sessions or test_sessions[test_id]['status'] != 'active':
        await query.answer("⚠ Этот тест уже завершен", show_alert=True)
        return
    
    user = query.from_user
    user_mention = f"@{user.username}" if user.username else user.first_name
    
    # Обновляем статус теста
    test_sessions[test_id]['status'] = 'in_progress'
    test_sessions[test_id]['user_data'] = {
        'id': user.id,
        'mention': user_mention,
        'photo': None,
        'number': None
    }
    
    # Обновляем сообщение с тестом
    await query.edit_message_text(
        text=f"{query.message.text}\n\n👤 Выполняет: {user_mention}",
        reply_markup=None
    )
    
    # Просим прислать данные для теста
    await context.bot.send_message(
        chat_id=TARGET_GROUP_ID,
        text=f"{user_mention}, для выполнения отправьте:\n1. Скриншот выполнения\n2. Последние 4 цифры номера",
        message_thread_id=TARGET_TOPIC_ID
    )

async def handle_test_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает скриншот и номер от пользователя"""
    try:
        user_id = update.effective_user.id
        
        # Ищем активный тест для этого пользователя
        test_id = next((k for k, v in test_sessions.items() 
                      if v['status'] == 'in_progress' and v['user_data']['id'] == user_id), None)
        
        if not test_id:
            logger.warning(f"Активный тест не найден для пользователя {user_id}")
            return
        
        test = test_sessions[test_id]
        
        if update.message.photo:
            # Берем фото среднего качества (не самое большое)
            photo = update.message.photo[1]
            test['user_data']['photo'] = photo.file_id
            logger.info(f"Скриншот сохранен для теста {test_id}")
            await update.message.reply_text("✅ Скриншот получен! Теперь отправьте 4 цифры номера.")
            
        elif update.message.text and len(update.message.text) == 4 and update.message.text.isdigit():
            # Сохраняем номер и отправляем на проверку
            test['user_data']['number'] = update.message.text
            
            # Кнопки для проверки теста
            keyboard = [
                [InlineKeyboardButton("✅ Тест пройден", callback_data=f"test_passed_{test_id}")],
                [InlineKeyboardButton("❌ Тест не пройден", callback_data=f"test_failed_{test_id}")]
            ]
            
            # Отправляем данные на проверку админу
            await context.bot.send_photo(
              chat_id=SOURCE_GROUP_ID,
              photo=test['user_data']['photo'],
              caption=(
              f"🛑 Проверка теста\n\n"
               f"Номер: {test['user_data']['number']}\n"
    ),
    reply_markup=InlineKeyboardMarkup(keyboard)
)
            
            await update.message.reply_text("✅ Данные отправлены на проверку!")
            
        elif update.message.text:
            await update.message.reply_text("❌ Нужно отправить ровно 4 цифры номера")
            
    except Exception as e:
        logger.error(f"Ошибка в handle_test_data: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при обработке данных. Попробуйте еще раз.")

async def handle_test_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает результат проверки теста админом"""
    try:
        query = update.callback_query
        await query.answer()
        
        action, test_id = query.data.split('_')[1], int(query.data.split('_')[-1])
        if test_id not in test_sessions:
            await query.answer("⚠ Тест не найден", show_alert=True)
            return
        
        test = test_sessions[test_id]
        user_mention = test['user_data']['mention']
        
        if action == "passed":
            # Тест пройден
            await context.bot.send_message(
                chat_id=TARGET_GROUP_ID,
                text=f"✅ Тест успешно пройден {user_mention}!",
                message_thread_id=TARGET_TOPIC_ID
            )
        else:
            # Тест не пройден - пересоздаем
            keyboard = [[InlineKeyboardButton("✅ Я выполню", callback_data=f"do_test_{test_id}")]]
            await context.bot.send_message(
                chat_id=TARGET_GROUP_ID,
                text=f"❌ Тест не пройден {user_mention}. ОТПРАВЛЯЕМ ЗАНОВО",
                message_thread_id=TARGET_TOPIC_ID
            )
            
            # Пересоздаем тест
            await context.bot.send_message(
                chat_id=TARGET_GROUP_ID,
                text=f"🛑 ЗАДАНИЕ 🛑\n\n{test['text']}",
                message_thread_id=TARGET_TOPIC_ID,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # Сбрасываем статус теста
            test_sessions[test_id]['status'] = 'active'
            test_sessions[test_id]['user_data'] = None
        
        # Удаляем сообщение с кнопками проверки
        await query.message.edit_reply_markup(reply_markup=None)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_test_verification: {e}", exc_info=True)
        await query.answer("⚠ Произошла ошибка", show_alert=True)

async def cancel_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет создание теста"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Создание теста отменено")
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)

# ===== ЗАПУСК БОТА =====
def main() -> None:
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Обработчик тестов
    test_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('test', start_test)],
        states={
            "AWAIT_TEST_TEXT": [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_test_text)],
        },
        fallbacks=[CallbackQueryHandler(cancel_test, pattern="^cancel_test$")],
    )
    
    application.add_handler(test_conv_handler)
    application.add_handler(CallbackQueryHandler(start_test_execution, pattern="^do_test_"))
    application.add_handler(CallbackQueryHandler(handle_test_verification, pattern="^test_(passed|failed)_"))
    
    # Обработчик данных теста (скриншоты и номера)
    application.add_handler(MessageHandler(
        filters.Chat(TARGET_GROUP_ID) & (filters.PHOTO | filters.TEXT),
        handle_test_data
    ))
    
    application.add_error_handler(error_handler)
    
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()