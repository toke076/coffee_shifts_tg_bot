import logging
import os
from dotenv import load_dotenv
from typing import List
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
load_dotenv()
# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Токен не найден! Создайте файл .env с BOT_TOKEN")
# ===============================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Чек-листы ----------
OPENING_TASKS: List[str] = [
    "☕ Включить кофемашину и прогреть",
    "🥛 Проверить наличие молока",
    "🍬 Проверить наличие сиропов",
    "🧼 Включить посудомоечную машину",
    "🍰 Разложить товар на витрине",
    "💰 Проверить кассу (размен, чековая лента)",
    "🧹 Быстрая уборка рабочей зоны",
    "🚪 Открыть входную дверь",
]

CLOSING_TASKS: List[str] = [
    "☕ Выключить кофемашину и очистить",
    "🧽 Помыть оборудование (кофемолка, питчеры)",
    "🍰 Убрать товар с витрины в холодильник",
    "🧼 Выключить посудомоечную машину",
    "💰 Снять кассу и закрыть смену",
    "🗑 Вынести мусор",
    "💡 Выключить свет",
    "🔒 Закрыть входную дверь",
]

# ---------- Состояния конечного автомата ----------
(
    SELECTING_ACTION,  # выбор открытие/закрытие
    ASK_NAME,          # запрос имени
    ASKING_TASKS,      # прохождение чек-листа
) = range(3)

# ---------- Вспомогательные функции ----------
def get_task_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопками Да/Нет"""
    buttons = [
        [
            InlineKeyboardButton("✅ Да", callback_data="yes"),
            InlineKeyboardButton("❌ Нет", callback_data="no"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_start_keyboard() -> ReplyKeyboardMarkup:
    """Стартовая клавиатура с выбором смены"""
    keyboard = [
        [KeyboardButton("🚀 Открытие смены")],
        [KeyboardButton("🔚 Закрытие смены")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# ---------- Обработчики ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — выбор действия"""
    await update.message.reply_text(
        "☕ Добро пожаловать в помощник смены!\n"
        "Выберите действие:",
        reply_markup=get_start_keyboard(),
    )
    return SELECTING_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена текущего диалога"""
    await update.message.reply_text(
        "❌ Операция отменена. Для начала работы нажмите /start",
        reply_markup=get_start_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END

async def action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора типа смены"""
    text = update.message.text
    if "Открытие" in text:
        context.user_data["shift_type"] = "открытия"
        context.user_data["tasks"] = OPENING_TASKS.copy()
    elif "Закрытие" in text:
        context.user_data["shift_type"] = "закрытия"
        context.user_data["tasks"] = CLOSING_TASKS.copy()
    else:
        await update.message.reply_text(
            "Пожалуйста, выберите действие из клавиатуры.",
            reply_markup=get_start_keyboard(),
        )
        return SELECTING_ACTION

    # Запрос имени — клавиатура убирается
    await update.message.reply_text(
        "👤 Введите ваше имя (или никнейм):",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_NAME

async def process_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Сохранение имени и запуск чек-листа"""
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Имя не может быть пустым. Пожалуйста, введите имя:")
        return ASK_NAME

    context.user_data["employee_name"] = name
    context.user_data["answers"] = []
    context.user_data["checklist_lines"] = []
    context.user_data["current_index"] = 0
    context.user_data["checklist_message_id"] = None

    # Отправляем первое сообщение чек-листа
    await send_or_update_checklist(update, context, is_new=True)
    return ASKING_TASKS

async def send_or_update_checklist(
    update: Update, context: ContextTypes.DEFAULT_TYPE, is_new: bool = False
) -> None:
    """
    Отправляет новое или редактирует существующее сообщение с чек-листом.
    """
    user_data = context.user_data
    shift_type = user_data["shift_type"]
    name = user_data["employee_name"]
    tasks = user_data["tasks"]
    idx = user_data["current_index"]
    answers = user_data["answers"]
    lines = user_data["checklist_lines"]

    # Заголовок
    header = f"📋 Чек-лист {shift_type} смены\n👤 Сотрудник: {name}\n\n"

    # Выполненные пункты
    completed_text = ""
    if lines:
        completed_text = "\n".join(lines) + "\n\n"

    # Текущий вопрос или итог
    question_text = ""
    keyboard = None
    total = len(tasks)

    if idx < total:
        task = tasks[idx]
        question_text = f"Вопрос {idx+1}/{total}:\n{task}\n\nВыполнено?"
        keyboard = get_task_keyboard()
    else:
        # Формируем итог
        completed = []
        failed = []
        for i, (task, done) in enumerate(zip(tasks, answers)):
            if done:
                completed.append(f"✅ {i+1}. {task}")
            else:
                failed.append(f"❌ {i+1}. {task}")

        if failed:
            result_text = "⚠️ **Не выполнено:**\n" + "\n".join(failed)
        else:
            result_text = "🎉 **Все пункты выполнены! Отличная работа!**"

        question_text = f"\n🏁 **Чек-лист завершён!**\n\n{result_text}"
        keyboard = None

    full_text = header + completed_text + question_text

    if is_new:
        # Отправляем новое сообщение
        sent = await update.message.reply_text(
            full_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        user_data["chat_id"] = sent.chat_id
        user_data["checklist_message_id"] = sent.message_id
    else:
        # Редактируем существующее
        chat_id = user_data["chat_id"]
        message_id = user_data["checklist_message_id"]
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=full_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответа Да/Нет через inline-кнопки"""
    query = update.callback_query
    await query.answer()

    user_data = context.user_data
    answer = query.data == "yes"
    user_data["answers"].append(answer)

    idx = user_data["current_index"]
    tasks = user_data["tasks"]
    task = tasks[idx]
    status = "✅" if answer else "❌"
    line = f"{status} {idx+1}. {task}"
    user_data["checklist_lines"].append(line)

    user_data["current_index"] += 1

    await send_or_update_checklist(query, context, is_new=False)

    if user_data["current_index"] >= len(tasks):
        # Чек-лист завершён
        return ConversationHandler.END
    else:
        return ASKING_TASKS

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Если пользователь пишет текст вместо кнопки"""
    await update.message.reply_text(
        "⚠️ Пожалуйста, используйте кнопки для ответа.",
        reply_markup=None,
    )
    return ASKING_TASKS

def main() -> None:
    """Запуск бота"""
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(🚀 Открытие смены|🔚 Закрытие смены)$"), action_chosen),
        ],
        states={
            SELECTING_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, action_chosen)
            ],
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_name)
            ],
            ASKING_TASKS: [
                CallbackQueryHandler(handle_answer, pattern="^(yes|no)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        # per_message не указываем (по умолчанию False) — работает корректно
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("cancel", cancel))  # вне диалога

    application.run_polling()

if __name__ == "__main__":
    main()