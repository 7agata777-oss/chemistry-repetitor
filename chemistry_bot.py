import asyncio
import logging
import os
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

# Токен из переменной окружения (Render)
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ---- Состояния FSM ----
class Quiz(StatesGroup):
    main_menu = State()
    show_theory = State()
    question_index = State()
    correct_count = State()

# ---- Зачётная книжка (в памяти) ----
user_progress = {}

# ---- Темы, теория и вопросы ----
TOPICS = {
    "atom_structure": {
        "title": "Строение атома",
        "theory": (
            "⚛️ **Строение атома**\n\n"
            "Атом состоит из ядра и электронной оболочки.\n"
            "• Ядро: протоны (+) и нейтроны (0).\n"
            "• Число протонов = порядковый номер элемента.\n"
            "• Число электронов = число протонов (атом электронейтрален).\n"
            "• Электроны располагаются на энергетических уровнях (слоях).\n"
            "• Максимальное число электронов на уровне: 2n².\n\n"
            "Пример: углерод (C), Z=6 → 6 протонов, 6 электронов.\n"
            "Распределение: 2, 4."
        ),
        "questions": [
            {
                "q": "Сколько протонов в атоме углерода (C)?",
                "options": ["6", "12", "8", "14"],
                "correct": 0
            },
            {
                "q": "Какой заряд у электрона?",
                "options": ["положительный", "отрицательный", "нейтральный", "зависит от атома"],
                "correct": 1
            },
            {
                "q": "Что находится в ядре атома?",
                "options": ["электроны", "протоны и нейтроны", "только протоны", "нейтроны и электроны"],
                "correct": 1
            }
        ]
    },
    "chemical_bond": {
        "title": "Химическая связь",
        "theory": (
            "🔗 **Химическая связь**\n\n"
            "• **Ионная**: между металлом и неметаллом (NaCl).\n"
            "• **Ковалентная полярная**: между разными неметаллами (HCl).\n"
            "• **Ковалентная неполярная**: между одинаковыми неметаллами (O₂).\n"
            "• **Металлическая**: в металлах.\n\n"
            "Электроотрицательность (ЭО) помогает определить тип связи."
        ),
        "questions": [
            {
                "q": "Какая связь в молекуле NaCl?",
                "options": ["ковалентная полярная", "ионная", "ковалентная неполярная", "металлическая"],
                "correct": 1
            },
            {
                "q": "Тип связи в молекуле O₂?",
                "options": ["ионная", "ковалентная полярная", "ковалентная неполярная", "водородная"],
                "correct": 2
            },
            {
                "q": "Что такое ковалентная полярная связь?",
                "options": [
                    "связь между одинаковыми неметаллами",
                    "связь между металлом и неметаллом",
                    "связь между разными неметаллами",
                    "связь в металлах"
                ],
                "correct": 2
            }
        ]
    },
    "reactions": {
        "title": "Реакции и уравнения",
        "theory": (
            "🧪 **Химические реакции**\n\n"
            "• Реакция – превращение веществ.\n"
            "• Уравнение показывает реагенты и продукты.\n"
            "• Коэффициенты уравнивают число атомов.\n"
            "• Тепловой эффект: экзо- (выделение тепла) и эндотермические (поглощение).\n"
            "• Типы: соединения, разложения, замещения, обмена."
        ),
        "questions": [
            {
                "q": "Сумма коэффициентов в реакции 2H₂ + O₂ → 2H₂O равна:",
                "options": ["3", "4", "5", "6"],
                "correct": 2
            },
            {
                "q": "Реакция, при которой выделяется тепло, называется:",
                "options": ["эндотермическая", "экзотермическая", "каталитическая", "обратимая"],
                "correct": 1
            },
            {
                "q": "Что получится в реакции NaOH + HCl → ?",
                "options": ["NaCl + H₂O", "NaCl + O₂", "Na + Cl₂ + H₂O", "H₂O + Cl₂"],
                "correct": 0
            }
        ]
    },
    "substance_classes": {
        "title": "Основные классы веществ",
        "theory": (
            "📚 **Классы неорганических веществ**\n\n"
            "• **Оксиды**: состоят из двух элементов, один – кислород (SO₂, CaO).\n"
            "• **Основания**: металл + гидроксогруппа OH (NaOH).\n"
            "• **Кислоты**: водород + кислотный остаток (HCl, H₂SO₄).\n"
            "• **Соли**: металл + кислотный остаток (NaCl, CaCO₃).\n\n"
            "Генетическая связь: металл → оксид → основание → соль."
        ),
        "questions": [
            {
                "q": "Какой оксид соответствует серной кислоте H₂SO₄?",
                "options": ["SO₂", "SO₃", "H₂O", "SO"],
                "correct": 1
            },
            {
                "q": "Формула гидроксида кальция:",
                "options": ["CaOH", "Ca(OH)₂", "Ca₂OH", "CaO"],
                "correct": 1
            },
            {
                "q": "Соли — это:",
                "options": [
                    "продукты замещения водорода кислоты металлом",
                    "вещества, состоящие из двух элементов",
                    "соединения металлов с кислородом",
                    "продукты взаимодействия кислоты и основания"
                ],
                "correct": 0
            }
        ]
    },
    "electrolytic_dissociation": {
        "title": "Электролитическая диссоциация",
        "theory": (
            "💧 **Электролитическая диссоциация**\n\n"
            "• Электролиты – вещества, растворы которых проводят ток.\n"
            "• Диссоциация – распад на ионы под действием воды.\n"
            "• Сильные электролиты: HCl, NaOH, NaCl.\n"
            "• Слабые: H₂CO₃, NH₃·H₂O.\n"
            "• Степень диссоциации α – доля распавшихся молекул."
        ),
        "questions": [
            {
                "q": "Какое вещество является электролитом?",
                "options": ["сахар", "спирт", "соляная кислота", "бензин"],
                "correct": 2
            },
            {
                "q": "Что образуется при диссоциации NaCl?",
                "options": ["Na⁺ + Cl⁻", "Na + Cl₂", "NaOH + HCl", "NaO + Cl"],
                "correct": 0
            },
            {
                "q": "Сильный электролит:",
                "options": ["H₂CO₃", "NH₃·H₂O", "NaOH", "уксусная кислота"],
                "correct": 2
            }
        ]
    },
    "redox": {
        "title": "Окислительно-восстановительные реакции",
        "theory": (
            "🔄 **ОВР**\n\n"
            "• Окисление – отдача электронов, восстановитель.\n"
            "• Восстановление – приём электронов, окислитель.\n"
            "• Степень окисления – условный заряд.\n"
            "• Метод электронного баланса помогает расставлять коэффициенты."
        ),
        "questions": [
            {
                "q": "В реакции Zn + 2HCl → ZnCl₂ + H₂ цинк:",
                "options": ["окисляется", "восстанавливается", "не изменяется", "является окислителем"],
                "correct": 0
            },
            {
                "q": "Степень окисления кислорода в H₂O:",
                "options": ["-2", "+2", "0", "-1"],
                "correct": 0
            },
            {
                "q": "Окислитель — это вещество, которое:",
                "options": ["отдаёт электроны", "принимает электроны", "не меняет заряд", "содержит водород"],
                "correct": 1
            }
        ]
    },
    "metals": {
        "title": "Металлы",
        "theory": (
            "🔩 **Металлы**\n\n"
            "• Обладают металлическим блеском, пластичностью, электро- и теплопроводностью.\n"
            "• В реакциях – восстановители.\n"
            "• Ряд активности металлов: Li, K, Ca, Na, Mg, Al, Zn, Fe, Pb, (H), Cu, Hg, Ag, Au.\n"
            "• Щелочные металлы активно реагируют с водой."
        ),
        "questions": [
            {
                "q": "Какой металл самый активный?",
                "options": ["Au", "Fe", "K", "Cu"],
                "correct": 2
            },
            {
                "q": "Металлы в реакциях обычно:",
                "options": ["принимают электроны", "отдают электроны", "не изменяются", "являются окислителями"],
                "correct": 1
            },
            {
                "q": "Что образуется при реакции натрия с водой?",
                "options": ["Na₂O", "NaOH + H₂", "NaH", "NaCl"],
                "correct": 1
            }
        ]
    }
}

# ---- Клавиатура главного меню (Reply-кнопки) ----
def main_menu_kb():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Выбрать тему")],
            [KeyboardButton(text="📊 Зачётная книжка")],
            [KeyboardButton(text="📋 План занятий")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return kb

# Выбор темы – Inline-клавиатура
def topics_inline_kb():
    builder = InlineKeyboardBuilder()
    for topic_id, data in TOPICS.items():
        builder.button(text=data["title"], callback_data=f"select_{topic_id}")
    builder.adjust(1)
    return builder.as_markup()

# Клавиатура действий с темой: Теория, Тест, Назад
def topic_actions_kb(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="📘 Теория", callback_data=f"theory_{topic_id}")
    builder.button(text="📝 Тест", callback_data=f"test_{topic_id}")
    builder.button(text="🔙 Назад", callback_data="back_to_topics")
    builder.adjust(2, 1)
    return builder.as_markup()

# Клавиатура с ответами
def question_kb(topic_id: str, idx: int):
    q = TOPICS[topic_id]["questions"][idx]
    builder = InlineKeyboardBuilder()
    for i, option in enumerate(q["options"]):
        builder.button(text=option, callback_data=f"ans_{i}")
    builder.adjust(1)
    return builder.as_markup()

# Клавиатура после теста / теории
def after_action_kb(topic_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Тест по этой теме", callback_data=f"test_{topic_id}")
    builder.button(text="📋 Выбрать другую тему", callback_data="back_to_topics")
    builder.button(text="📊 Зачётная книжка", callback_data="progress")
    builder.adjust(1)
    return builder.as_markup()

# ---- Команда /start ----
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🧪 Привет! Я репетитор по химии для 9 класса.\n"
        "Выбери тему, чтобы изучить теорию или пройти тест.",
        reply_markup=main_menu_kb()
    )
    await state.set_state(Quiz.main_menu)

# ---- Главное меню: кнопка "Выбрать тему" ----
@dp.message(Quiz.main_menu, F.text == "📖 Выбрать тему")
async def show_topics(message: types.Message, state: FSMContext):
    await message.answer("📚 Доступные темы:", reply_markup=topics_inline_kb())

# ---- Главное меню: кнопка "Зачётная книжка" ----
@dp.message(Quiz.main_menu, F.text == "📊 Зачётная книжка")
async def show_progress_menu(message: types.Message, state: FSMContext):
    await show_progress(message.from_user.id, message)

# ---- Главное меню: кнопка "План занятий" ----
@dp.message(Quiz.main_menu, F.text == "📋 План занятий")
async def show_study_plan(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    lines = ["📋 **Ваш план занятий:**\n"]
    for topic_id, data in TOPICS.items():
        stats = user_progress.get(user_id, {}).get(topic_id, None)
        if stats:
            best = stats["best_percent"]
            attempts = stats["attempts"]
            lines.append(f"✅ {data['title']} — {best:.0f}% ({attempts} поп.)")
        else:
            lines.append(f"⬜ {data['title']} — не пройдена")
    text = "\n".join(lines)

    # Добавляем кнопки для быстрого перехода
    kb = topics_inline_kb()
    await message.answer(text, reply_markup=kb)

# ---- Обработка выбора темы (Inline) ----
@dp.callback_query(F.data.startswith("select_"))
async def select_topic(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    await state.update_data(current_topic=topic_id)
    topic_title = TOPICS[topic_id]["title"]
    await callback.message.edit_text(
        f"📘 Тема: **{topic_title}**\n\n"
        "Выбери действие:",
        reply_markup=topic_actions_kb(topic_id)
    )
    await callback.answer()

# ---- Кнопка "Теория" ----
@dp.callback_query(F.data.startswith("theory_"))
async def show_theory(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    data = TOPICS[topic_id]
    await callback.message.edit_text(
        data["theory"],
        reply_markup=after_action_kb(topic_id)
    )
    await callback.answer()

# ---- Кнопка "Тест" (начало) ----
@dp.callback_query(F.data.startswith("test_"))
async def start_test(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    await state.update_data(current_topic=topic_id, question_index=0, correct_count=0)
    q = TOPICS[topic_id]["questions"][0]
    await callback.message.edit_text(
        f"📝 Тест по теме «{TOPICS[topic_id]['title']}»\n\n"
        f"Вопрос 1:\n{q['q']}",
        reply_markup=question_kb(topic_id, 0)
    )
    await state.set_state(Quiz.question_index)
    await callback.answer()

# ---- Обработка ответа ----
@dp.callback_query(Quiz.question_index, F.data.startswith("ans_"))
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic_id = data["current_topic"]
    idx = data["question_index"]
    correct_count = data["correct_count"]

    user_choice = int(callback.data.split("_")[1])
    correct_idx = TOPICS[topic_id]["questions"][idx]["correct"]
    is_correct = (user_choice == correct_idx)

    if is_correct:
        correct_count += 1

    options = TOPICS[topic_id]["questions"][idx]["options"]
    correct_answer = options[correct_idx]

    feedback = "✅ Верно!" if is_correct else f"❌ Неверно. Правильный ответ: {correct_answer}"
    result_text = f"Вопрос {idx+1}:\n{TOPICS[topic_id]['questions'][idx]['q']}\n\nВаш ответ: {options[user_choice]}\n{feedback}"

    idx += 1
    if idx < len(TOPICS[topic_id]["questions"]):
        await state.update_data(question_index=idx, correct_count=correct_count)
        new_kb = question_kb(topic_id, idx)
        await callback.message.edit_text(
            f"{result_text}\n\nПереходим к вопросу {idx+1}...",
            reply_markup=new_kb
        )
    else:
        total = len(TOPICS[topic_id]["questions"])
        percent = (correct_count / total) * 100
        # обновляем зачётку
        user_id = callback.from_user.id
        if user_id not in user_progress:
            user_progress[user_id] = {}
        if topic_id not in user_progress[user_id]:
            user_progress[user_id][topic_id] = {"attempts": 0, "best_percent": 0.0}
        user_progress[user_id][topic_id]["attempts"] += 1
        if percent > user_progress[user_id][topic_id]["best_percent"]:
            user_progress[user_id][topic_id]["best_percent"] = percent

        await callback.message.edit_text(
            f"🎉 Тема пройдена!\n\n{result_text}\n\n"
            f"Правильных ответов: {correct_count} из {total} ({percent:.0f}%)",
            reply_markup=after_action_kb(topic_id)
        )
        await state.set_state(Quiz.main_menu)  # возвращаемся в меню после теста
    await callback.answer()

# ---- Кнопка "Назад" ----
@dp.callback_query(F.data == "back_to_topics")
async def back_to_topics(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📚 Доступные темы:", reply_markup=topics_inline_kb())
    await callback.answer()

# ---- Кнопка "Зачётная книжка" (Inline) ----
@dp.callback_query(F.data == "progress")
async def progress_inline(callback: types.CallbackQuery):
    await show_progress(callback.from_user.id, callback.message)
    await callback.answer()

# ---- Команда /progress ----
@dp.message(Command("progress"))
async def cmd_progress(message: types.Message):
    await show_progress(message.from_user.id, message)

# ---- Общая функция показа зачётки ----
async def show_progress(user_id: int, target):
    if user_id not in user_progress or not user_progress[user_id]:
        text = "📊 Зачётная книжка пуста. Пройдите хотя бы один тест!"
    else:
        lines = ["📊 **Зачётная книжка:**\n"]
        for topic_id, stats in user_progress[user_id].items():
            title = TOPICS[topic_id]["title"]
            lines.append(f"📘 {title}:")
            lines.append(f"   Попыток: {stats['attempts']} | Лучший результат: {stats['best_percent']:.0f}%")
        text = "\n".join(lines)
    if isinstance(target, types.Message):
        await target.answer(text)
    else:
        await target.message.answer(text)

# ---- Заглушка ----
@dp.message()
async def echo(message: types.Message, state: FSMContext):
    await message.answer("Для начала нажмите /start", reply_markup=main_menu_kb())

# ---- Запуск с веб-сервером (для Render) ----
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