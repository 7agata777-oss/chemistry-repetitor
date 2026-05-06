import asyncio
import logging
import os
import sqlite3
import re
import string
import datetime
from pathlib import Path
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---- База данных прогресса ----
DB_PATH = "progress.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    # Таблица для тем
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL,
            topic_id TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            best_percent REAL DEFAULT 0.0,
            PRIMARY KEY (user_id, topic_id)
        )
    """)
    # Таблица пользователей (для умного приветствия)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_seen TEXT,
            last_seen TEXT
        )
    """)
    # Таблица попыток ОГЭ
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oge_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT,
            question_text TEXT,
            user_answer TEXT,
            correct_answer TEXT,
            is_correct INTEGER DEFAULT 0,
            attempt_number INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def load_progress():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT user_id, topic_id, attempts, best_percent FROM progress")
    data = {}
    for uid, tid, att, pct in cur.fetchall():
        data.setdefault(uid, {})[tid] = {"attempts": att, "best_percent": pct}
    conn.close()
    return data

def save_progress(user_id, topic_id, attempts, best_percent):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO progress (user_id, topic_id, attempts, best_percent)
        VALUES (?,?,?,?) ON CONFLICT(user_id, topic_id) DO UPDATE SET
        attempts=excluded.attempts, best_percent=excluded.best_percent""",
        (user_id, topic_id, attempts, best_percent))
    conn.commit()
    conn.close()

def get_or_create_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT first_seen FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    now = datetime.datetime.utcnow().isoformat()
    if row:
        conn.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
        conn.commit()
        conn.close()
        return False  # уже был
    else:
        conn.execute("INSERT INTO users (user_id, first_seen, last_seen) VALUES (?,?,?)", (user_id, now, now))
        conn.commit()
        conn.close()
        return True   # новый

def save_oge_attempt(user_id, topic, question_text, user_answer, correct_answer, is_correct, attempt_number):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO oge_attempts (user_id, topic, question_text, user_answer, correct_answer, is_correct, attempt_number, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (user_id, topic, question_text, user_answer, correct_answer, int(is_correct), attempt_number, datetime.datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def load_oge_progress(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        SELECT topic, COUNT(*) as total, SUM(is_correct) as correct
        FROM oge_attempts WHERE user_id=?
        GROUP BY topic
    """, (user_id,))
    data = {}
    for topic, total, correct in cur.fetchall():
        data[topic] = {"total": total, "correct": correct}
    conn.close()
    return data

init_db()
user_progress = load_progress()

# ---- Загрузка учебника (ТОЛЬКО TXT) ----
textbook_paragraphs = []

def load_textbook():
    global textbook_paragraphs
    try:
        with open("chemistry_textbook.txt", "r", encoding="utf-8") as f:
            full = f.read()
        paragraphs = []
        for part in full.split("\n\n"):
            part = part.strip()
            if len(part) > 50:
                paragraphs.append(part)
            else:
                for sent in part.split("."):
                    sent = sent.strip()
                    if len(sent) > 20:
                        paragraphs.append(sent + ".")
        textbook_paragraphs = paragraphs
        logging.info(f"Учебник загружен, абзацев: {len(textbook_paragraphs)}")
    except Exception as e:
        logging.error(f"Ошибка загрузки учебника: {e}")

load_textbook()

# ---- УЛУЧШЕННЫЙ ПОИСК (без стоп-слов и знаков препинания) ----
def search_textbook(query: str) -> str:
    if not textbook_paragraphs:
        return ""
    translator = str.maketrans('', '', string.punctuation + '«»—–…')
    cleaned = query.translate(translator)
    stop_words = {
        "что", "такое", "как", "зачем", "почему", "кто", "где", "когда",
        "чей", "который", "для", "это", "в", "на", "по", "с", "и", "а", "но",
        "или", "не", "он", "она", "оно", "они", "его", "её", "их", "то",
        "от", "до", "из", "при", "без", "под", "над", "об", "во", "со",
        "ли", "же", "бы", "весь", "весьма", "очень", "самый", "каждый",
        "любой", "мой", "твой", "наш", "ваш", "себя", "меня", "тебя",
        "нам", "вам", "мне", "тебе", "нас", "вас"
    }
    words = cleaned.lower().split()
    significant = [w for w in words if w not in stop_words]
    if not significant:
        significant = words
    res = [p for p in textbook_paragraphs if all(w in p.lower() for w in significant)]
    if not res:
        res = [p for p in textbook_paragraphs if any(w in p.lower() for w in significant)]
    result = "\n\n".join(res[:3]) if res else ""
    if len(result) > 3500:
        result = result[:3500] + "\n\n... (текст обрезан, уточните вопрос, чтобы увидеть полный ответ)"
    return result

# ---- Состояния FSM ----
class Quiz(StatesGroup):
    main_menu = State()
    show_theory = State()
    question_index = State()
    correct_count = State()
    task_answer = State()

class OgeQuiz(StatesGroup):
    waiting_first_answer = State()
    waiting_second_answer = State()
    waiting_reasoning = State()

# ---- ПОЛНЫЙ СЛОВАРЬ ВСЕХ ТЕМ ----
TOPICS = {
    # ... весь словарь TOPICS без изменений (вставь свой тот же самый словарь, что был)
    # Я заменю его на сокращённую версию для экономии места, но ты оставь как у тебя.
    "classification_inorganic": {
        "title": "Классификация неорганических соединений",
        "theory": "📚 **Классификация неорганических соединений**\n\n...",
        "questions": [...]
    },
    # и так далее – оставь всё как было
}

# ---- Клавиатуры ----
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Выбрать тему")],
            [KeyboardButton(text="📊 Зачётная книжка")],
            [KeyboardButton(text="📋 План занятий")],
            [KeyboardButton(text="🔍 Задать вопрос")],
            [KeyboardButton(text="🎯 Подготовка к ОГЭ")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def topics_inline_kb():
    builder = InlineKeyboardBuilder()
    for topic_id, data in TOPICS.items():
        builder.button(text=data["title"], callback_data=f"select_{topic_id}")
    builder.adjust(1)
    return builder.as_markup()

def topic_actions_kb(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Теория", callback_data=f"theory_{topic_id}")
    if TOPICS[topic_id].get("questions"):
        builder.button(text="📝 Тест", callback_data=f"test_{topic_id}")
    if "tasks" in TOPICS[topic_id]:
        builder.button(text="📝 Задачи", callback_data=f"tasks_{topic_id}")
    builder.button(text="🔙 Назад", callback_data="back_to_topics")
    builder.adjust(2, 1)
    return builder.as_markup()

def question_kb(topic_id: str, idx: int):
    q = TOPICS[topic_id]["questions"][idx]
    builder = InlineKeyboardBuilder()
    for i, option in enumerate(q["options"]):
        builder.button(text=option, callback_data=f"ans_{i}")
    builder.adjust(1)
    return builder.as_markup()

def after_action_kb(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Тест по этой теме", callback_data=f"test_{topic_id}")
    if "tasks" in TOPICS[topic_id]:
        builder.button(text="📝 Задачи", callback_data=f"tasks_{topic_id}")
    builder.button(text="📋 Выбрать другую тему", callback_data="back_to_topics")
    builder.button(text="📊 Зачётная книжка", callback_data="progress")
    builder.button(text="🔙 Назад", callback_data="back_to_topics")
    builder.adjust(1)
    return builder.as_markup()

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    is_new = get_or_create_user(user_id)
    if is_new:
        welcome_text = (
            "🧪 Привет! Я репетитор по химии для 9 класса.\n"
            "Я помогу тебе подготовиться к ОГЭ, изучить теорию и решать задачи.\n"
            "Выбери действие в меню:"
        )
    else:
        welcome_text = "👋 С возвращением! Я готов продолжать обучение. Выбери действие в меню."
    await message.answer(welcome_text, reply_markup=main_menu_kb())
    await state.set_state(Quiz.main_menu)

@dp.message(Quiz.main_menu, F.text == "📖 Выбрать тему")
async def show_topics(message: types.Message, state: FSMContext):
    await message.answer("📚 Доступные темы:", reply_markup=topics_inline_kb())

@dp.message(Quiz.main_menu, F.text == "📊 Зачётная книжка")
async def show_progress_menu(message: types.Message, state: FSMContext):
    await show_progress(message.from_user.id, message)

@dp.message(Quiz.main_menu, F.text == "📋 План занятий")
async def show_study_plan(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lines = ["📋 **Ваш план занятий:**\n"]
    for topic_id, data in TOPICS.items():
        stats = user_progress.get(user_id, {}).get(topic_id)
        if stats:
            lines.append(f"✅ {data['title']} — {stats['best_percent']:.0f}% ({stats['attempts']} поп.)")
        else:
            lines.append(f"⬜ {data['title']} — не пройдена")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu_kb())

@dp.message(Quiz.main_menu, F.text == "🔍 Задать вопрос")
async def ask_question_start(message: types.Message, state: FSMContext):
    await message.answer(
        "Напишите ваш вопрос по химии, и я найду ответ в учебнике.",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Quiz.main_menu)

@dp.message(Quiz.main_menu, F.text)
async def handle_free_question(message: types.Message, state: FSMContext):
    question = message.text.strip()
    found = search_textbook(question)
    if found:
        await message.answer(f"📖 Найдено в учебнике:\n\n{found}", parse_mode="Markdown")
    else:
        await message.answer("К сожалению, я не нашёл ответа. Попробуй переформулировать вопрос.")
    await message.answer("Возвращаемся в меню.", reply_markup=main_menu_kb())

# --- ОГЭ ---
@dp.message(Quiz.main_menu, F.text == "🎯 Подготовка к ОГЭ")
async def oge_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Задания по линиям", callback_data="oge_lines")],
        [InlineKeyboardButton(text="📊 Мой прогресс ОГЭ", callback_data="oge_progress")]
    ])
    await message.answer("Выбери режим подготовки к ОГЭ:", reply_markup=keyboard)

@dp.callback_query(F.data == "oge_lines")
async def oge_lines_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Линия 1 (хим. элемент/вещество)", callback_data="oge_line_1")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main_menu")]
    ])
    await callback.message.edit_text("Выбери линию заданий:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data == "oge_line_1")
async def oge_line_1_start(callback: types.CallbackQuery, state: FSMContext):
    question = (
        "Выберите два утверждения, в которых говорится об азоте как о простом веществе.\n"
        "1) Азот необходим растениям для образования хлорофилла.\n"
        "2) Азот в промышленности получают фракционной перегонкой жидкого воздуха.\n"
        "3) В жидком состоянии азот бесцветен и подвижен, как вода.\n"
        "4) Содержание азота в почвах колеблется от 0,07 до 0,5 %.\n"
        "5) Валентность азота в ионе аммония равна IV."
    )
    correct = "23"
    await state.update_data(correct=correct, question=question, topic="oge_line_1")
    await callback.message.answer(question)
    await callback.message.answer("Введи две цифры правильных ответов (например, 23):")
    await state.set_state(OgeQuiz.waiting_first_answer)
    await callback.answer()

@dp.message(OgeQuiz.waiting_first_answer)
async def first_attempt_oge(message: types.Message, state: FSMContext):
    data = await state.get_data()
    correct = set(data["correct"])
    user_answer = message.text.strip()
    if len(user_answer) != 2 or not user_answer.isdigit():
        await message.answer("Нужно ввести ровно две цифры. Попробуй ещё раз (это первая попытка).")
        return
    is_correct = set(user_answer) == correct
    save_oge_attempt(message.from_user.id, "oge_line_1", data["question"], user_answer, data["correct"], is_correct, 1)
    if is_correct:
        await message.answer("✅ Верно! Молодец.")
        await state.clear()
        await message.answer("Возвращаемся в меню.", reply_markup=main_menu_kb())
    else:
        await message.answer("❌ Пока неверно. Расскажи, как ты рассуждал(а)? Напиши коротко, и я помогу найти ошибку.")
        await state.set_state(OgeQuiz.waiting_reasoning)

@dp.message(OgeQuiz.waiting_reasoning)
async def reasoning_step(message: types.Message, state: FSMContext):
    # Здесь мог бы быть запрос к DeepSeek с reasoning пользователя
    hint = (
        "Подумай: простое вещество — это то, что существует в виде конкретного вещества (газ, металл). "
        "Химический элемент — абстрактное понятие, вид атомов. Какие утверждения описывают именно вещество азот?"
    )
    await message.answer(hint)
    await message.answer("Теперь дай новый ответ (две цифры):")
    await state.set_state(OgeQuiz.waiting_second_answer)

@dp.message(OgeQuiz.waiting_second_answer)
async def second_attempt_oge(message: types.Message, state: FSMContext):
    data = await state.get_data()
    correct = set(data["correct"])
    user_answer = message.text.strip()
    if len(user_answer) != 2 or not user_answer.isdigit():
        await message.answer("Введи ровно две цифры (вторая попытка).")
        return
    is_correct = set(user_answer) == correct
    save_oge_attempt(message.from_user.id, "oge_line_1", data["question"], user_answer, data["correct"], is_correct, 2)
    if is_correct:
        await message.answer("✅ Теперь верно! Отлично.")
    else:
        await message.answer(f"❌ К сожалению, правильный ответ: {data['correct']} (утверждения 2 и 3).")
    # Объяснение от DeepSeek (заглушка)
    explanation = "Азот как простое вещество — это газ N₂, бесцветный, без запаха, получают из жидкого воздуха. Утверждения 2 и 3 описывают его свойства, а остальные — химический элемент."
    await message.answer(f"📚 Пояснение:\n{explanation}")
    await state.clear()
    await message.answer("Что дальше?", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "oge_progress")
async def show_oge_progress(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = load_oge_progress(user_id)
    if not stats:
        await callback.message.answer("Ты ещё не решал(а) задания ОГЭ.")
    else:
        text = "📊 Твой прогресс по ОГЭ:\n"
        for topic, s in stats.items():
            text += f"{topic}: решено {s['total']} задач, правильно {s['correct']}\n"
        await callback.message.answer(text)
    await callback.answer()

# Остальные хендлеры из старого кода (тесты, теория и т.д.) – вставь их как были
# ...

# ---- Загрузка справочников ----
reference_data = {}

def load_reference_books(folder='data'):
    data_path = Path(folder)
    if not data_path.exists():
        print(f"Папка {folder} не найдена")
        return
    for file in data_path.glob('*.txt'):
        with open(file, 'r', encoding='utf-8') as f:
            reference_data[file.name] = f.read()
        print(f"Загружен: {file.name}")

load_reference_books('data')

# Запуск
async def main():
    app = web.Application()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())