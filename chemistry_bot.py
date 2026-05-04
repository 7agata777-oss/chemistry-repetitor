import asyncio
import logging
import os
import sqlite3
import re
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL,
            topic_id TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            best_percent REAL DEFAULT 0.0,
            PRIMARY KEY (user_id, topic_id)
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

# ---- УЛУЧШЕННЫЙ ПОИСК С ФИЛЬТРАЦИЕЙ СТОП-СЛОВ ----
def search_textbook(query: str) -> str:
    if not textbook_paragraphs:
        return ""
    stop_words = {
        "что", "такое", "как", "зачем", "почему", "кто", "где", "когда",
        "чей", "который", "для", "это", "в", "на", "по", "с", "и", "а", "но",
        "или", "не", "он", "она", "оно", "они", "его", "её", "их", "то",
        "от", "до", "из", "при", "без", "под", "над", "об", "во", "со",
        "ли", "же", "бы", "весь", "весьма", "очень", "самый", "каждый",
        "любой", "мой", "твой", "наш", "ваш", "себя", "меня", "тебя",
        "нам", "вам", "мне", "тебе", "нас", "вас"
    }
    words = query.lower().split()
    significant = [w for w in words if w not in stop_words]
    if not significant:
        significant = words
    # Сначала точный поиск (все значимые слова присутствуют)
    res = [p for p in textbook_paragraphs if all(w in p.lower() for w in significant)]
    if not res:
        # Если точных совпадений нет – ищем хотя бы одно значимое слово
        res = [p for p in textbook_paragraphs if any(w in p.lower() for w in significant)]
    result = "\n\n".join(res[:3]) if res else ""
    if len(result) > 3500:
        result = result[:3500] + "... (текст обрезан, уточните вопрос)"
    return result

# ---- Состояния FSM ----
class Quiz(StatesGroup):
    main_menu = State()
    show_theory = State()
    question_index = State()
    correct_count = State()
    task_answer = State()

# ---- ПОЛНЫЙ СЛОВАРЬ ВСЕХ ТЕМ (как в предыдущем коде) ----
TOPICS = {
    "classification_inorganic": {
        "title": "Классификация неорганических соединений",
        "theory": (
            "📚 **Классификация неорганических соединений**\n\n"
            "**Простые вещества** — образованы атомами одного элемента (металлы, неметаллы, благородные газы).\n"
            "**Сложные вещества** — из атомов разных элементов.\n\n"
            "**Бинарные соединения** (из двух элементов):\n"
            "• **Оксиды** — содержат кислород (ЭxOy). Делятся на:\n"
            "  - **Солеобразующие**: основные (Na₂O), кислотные (SO₃), амфотерные (Al₂O₃).\n"
            "  - **Несолеобразующие**: CO, NO, N₂O, SiO.\n"
            "• **Гидриды металлов** (NaH), **сульфиды** (FeS₂), **галогениды** (NaCl).\n\n"
            "**Гидроксиды** (продукты соединения оксидов с водой):\n"
            "• **Основания** — гидроксиды металлов IA и IIA групп (кроме Be) и некоторые другие: NaOH, Ca(OH)₂, Fe(OH)₂.\n"
            "• **Амфотерные гидроксиды** — Be(OH)₂, Al(OH)₃, Zn(OH)₂ и др.\n"
            "• **Кислородсодержащие кислоты** — H₂SO₄, HNO₃, H₃PO₄.\n\n"
            "**Соли** — продукты замещения водорода кислоты металлом:\n"
            "• Средние (NaCl, CaCO₃)\n"
            "• Кислые (NaHCO₃, KHSO₄)\n"
            "• Основные (MgOHCl)\n"
            "• Комплексные (K₄[Fe(CN)₆])\n\n"
            "**Агрегатное состояние** — твёрдые (кристаллические и аморфные), жидкие, газообразные.\n"
            "**Растворимость в воде** — растворимые (>1 г/100 г воды), малорастворимые (0,1–1 г), нерастворимые (<0,1 г)."
        ),
        "questions": [
            {"q": "Какой из перечисленных оксидов является кислотным?", "options": ["Na₂O", "CaO", "SO₃", "MgO"], "correct": 2},
            {"q": "Формула гидросульфата натрия:", "options": ["Na₂SO₄", "NaHSO₄", "Na₂S", "NaHS"], "correct": 1},
            {"q": "Амфотерный гидроксид — это:", "options": ["KOH", "Fe(OH)₂", "Zn(OH)₂", "Ba(OH)₂"], "correct": 2}
        ]
    },
    "classification_reactions": {
        "title": "Классификация химических реакций",
        "theory": (
            "🔄 **Классификация химических реакций**\n\n"
            "**1. По числу и составу реагентов и продуктов:**\n"
            "• **Соединения** — из двух или более веществ образуется одно сложное: S + O₂ → SO₂\n"
            "• **Разложения** — из одного сложного вещества образуются два или более: CaCO₃ → CaO + CO₂↑\n"
            "• **Замещения** — атом простого вещества замещает атом в сложном: Fe + CuSO₄ → Cu + FeSO₄\n"
            "• **Обмена** — два сложных вещества обмениваются составными частями: NaOH + HCl → NaCl + H₂O\n\n"
            "**2. По тепловому эффекту:**\n"
            "• **Экзотермические** (+Q, выделение тепла): горение, большинство реакций соединения.\n"
            "• **Эндотермические** (-Q, поглощение тепла): разложение многих веществ.\n"
            "Тепловой эффект обозначается Q (кДж).\n"
            "Термохимическое уравнение: H₂SO₄ + 2NaOH → Na₂SO₄ + 2H₂O + 114 кДж.\n\n"
            "**3. По агрегатному состоянию:**\n"
            "• **Гомогенные** — реагенты в одной фазе (газы или раствор): 2SO₂(г) + O₂(г) → 2SO₃(г)\n"
            "• **Гетерогенные** — реагенты в разных фазах: 4FeS₂(тв) + 11O₂(г) → 2Fe₂O₃ + 8SO₂\n\n"
            "**4. По обратимости:**\n"
            "• **Необратимые** — идут только в одном направлении: горение серы.\n"
            "• **Обратимые** — одновременно протекают в двух направлениях: 2SO₂ + O₂ ⇄ 2SO₃\n\n"
            "**5. По использованию катализатора:**\n"
            "• **Каталитические** (с катализатором): 2SO₂ + O₂ →(V₂O₅) 2SO₃\n"
            "• **Некаталитические**.\n"
            "• **Ферментативные** — биокатализаторы (ферменты).\n\n"
            "**6. По изменению степеней окисления:**\n"
            "• **Окислительно-восстановительные (ОВР)** — изменяются степени окисления элементов: Fe + CuSO₄ → FeSO₄ + Cu.\n"
            "• **Не ОВР** — степени окисления не меняются: NaOH + HCl → NaCl + H₂O."
        ),
        "questions": [
            {"q": "Реакция CaCO₃ → CaO + CO₂ относится к типу:", "options": ["соединения", "разложения", "замещения", "обмена"], "correct": 1},
            {"q": "Гомогенной является реакция:", "options": ["C + O₂ → CO₂", "Fe + S → FeS", "NaOH + HCl → NaCl + H₂O", "Zn + 2HCl → ZnCl₂ + H₂"], "correct": 2},
            {"q": "Экзотермическая реакция:", "options": ["N₂ + O₂ → 2NO", "CaCO₃ → CaO + CO₂", "CH₄ + 2O₂ → CO₂ + 2H₂O", "2H₂O → 2H₂ + O₂"], "correct": 2}
        ]
    },
    "reaction_rate": {
        "title": "Скорость химических реакций. Катализ",
        "theory": (
            "⏱ **Скорость химических реакций**\n\n"
            "**Скорость реакции** — изменение концентрации вещества в единицу времени: v = Δc / Δt (моль/л·с).\n\n"
            "**Факторы, влияющие на скорость:**\n"
            "• **Природа реагирующих веществ** (активность металлов, сила кислот).\n"
            "• **Температура** — при повышении на 10°С скорость увеличивается в 2–4 раза (правило Вант-Гоффа).\n"
            "• **Концентрация** — чем выше концентрация, тем больше скорость (закон действующих масс).\n"
            "• **Площадь соприкосновения** (для гетерогенных) — измельчение твёрдых веществ увеличивает скорость.\n"
            "• **Наличие катализатора** — вещество, ускоряющее реакцию, но не входящее в состав продуктов.\n\n"
            "**Катализ** — увеличение скорости в присутствии катализатора. Пример: разложение H₂O₂ ускоряется оксидом марганца(IV).\n"
            "**Ферменты** — биологические катализаторы белковой природы."
        ),
        "questions": [
            {"q": "Скорость гетерогенной реакции возрастёт при:", "options": ["понижении температуры", "измельчении твёрдого реагента", "уменьшении концентрации", "добавлении ингибитора"], "correct": 1},
            {"q": "Катализатор в реакции:", "options": ["расходуется полностью", "ускоряет реакцию, но не входит в состав продуктов", "замедляет реакцию", "всегда твёрдое вещество"], "correct": 1},
            {"q": "При повышении температуры на 20°С скорость большинства реакций увеличивается примерно в:", "options": ["1,5 раза", "2 раза", "4–16 раз", "100 раз"], "correct": 2}
        ],
        "tasks": {
            "example": "✏️ **Пример:** За 2 минуты концентрация реагента уменьшилась с 0,8 до 0,2 моль/л. v = (0,8-0,2)/2 = 0,3 моль/л·мин.",
            "formulas": "v = (Cнач - Cкон) / t",
            "problems": [
                {"question": "Концентрация вещества уменьшилась с 1,2 до 0,4 моль/л за 4 минуты. Чему равна скорость реакции?", "answer": "0,2 моль/л*мин", "explanation": "v = (1,2-0,4)/4 = 0,2 моль/л·мин."},
                {"question": "Для гетерогенной реакции взяли кусочек мрамора и порошок мрамора. С каким из них скорость взаимодействия с кислотой будет выше?", "answer": "с порошком", "explanation": "Измельчение увеличивает площадь поверхности соприкосновения."}
            ]
        }
    },
    # Остальные темы точно такие же, как в предыдущем полном коде
    # (electrolytic_dissociation, properties_acids, properties_bases, properties_salts,
    #  hydrolysis, halogens, sulfur, nitrogen, phosphorus, carbon, silicon,
    #  metals_general, alkali_metals, alkaline_earth_metals, aluminum, iron,
    #  organic, environment)
    # Их нужно вставить полностью, как раньше.
}

# ---- Клавиатуры (без изменений) ----
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Выбрать тему")],
            [KeyboardButton(text="📊 Зачётная книжка")],
            [KeyboardButton(text="📋 План занятий")],
            [KeyboardButton(text="🔍 Задать вопрос")],
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

# ========== ОБРАБОТЧИКИ (без изменений) ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🧪 Привет! Я репетитор по химии для 9 класса.\n"
        "Я могу провести тест, дать теорию или найти ответ в учебнике.\n"
        "Выберите действие:",
        reply_markup=main_menu_kb()
    )
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
        "Напишите ваш вопрос по химии, и я попробую найти ответ в учебнике.",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Quiz.main_menu)

@dp.message(Quiz.main_menu, F.text)
async def handle_free_question(message: types.Message, state: FSMContext):
    question = message.text.strip()
    found = search_textbook(question)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_topics")]
    ])
    if found:
        await message.answer(
            f"📖 Найдено в учебнике:\n\n{found}",
            parse_mode="Markdown", reply_markup=back_kb
        )
    else:
        await message.answer(
            "К сожалению, я не нашёл ответа в учебнике. "
            "Попробуйте переформулировать вопрос или выберите тему для изучения.",
            reply_markup=back_kb
        )

# Остальные обработчики те же, что и в последней полной версии
# (select_topic, show_theory, start_test, start_tasks, check_task_answer, process_answer,
# back_to_topics, progress_inline, cmd_progress, show_progress, echo, main)
# В реальном файле их нужно вставить полностью.

if __name__ == "__main__":
    asyncio.run(main())