import asyncio
import logging
import os
import sqlite3
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

# ---- Инициализация базы данных ----
DB_PATH = "progress.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
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

init_db()

def load_progress():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, topic_id, attempts, best_percent FROM progress")
    rows = cursor.fetchall()
    conn.close()
    data = {}
    for user_id, topic_id, attempts, best_percent in rows:
        data.setdefault(user_id, {})[topic_id] = {"attempts": attempts, "best_percent": best_percent}
    return data

def save_progress(user_id, topic_id, attempts, best_percent):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO progress (user_id, topic_id, attempts, best_percent)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, topic_id) DO UPDATE SET
            attempts = excluded.attempts,
            best_percent = excluded.best_percent
    """, (user_id, topic_id, attempts, best_percent))
    conn.commit()
    conn.close()

user_progress = load_progress()

# ---- Состояния FSM ----
class Quiz(StatesGroup):
    main_menu = State()
    show_theory = State()
    question_index = State()
    correct_count = State()
    task_answer = State()          # ожидание ответа на задачу

# ---- Расширенные материалы для подготовки к экзамену ----
TOPICS = {
    "atom_structure": {
        "title": "Строение атома",
        "theory": (
            "⚛️ **Строение атома**\n\n"
            "Атом — мельчайшая химически неделимая частица вещества. Состоит из положительно заряженного ядра и электронной оболочки.\n\n"
            "• **Ядро** содержит нуклоны: протоны (p⁺) с зарядом +1 и нейтроны (n⁰) без заряда. Массовое число A = Z + N (число протонов + число нейтронов).\n"
            "• **Электронная оболочка** — совокупность электронов (e⁻), движущихся вокруг ядра. Число электронов = числу протонов (атом электронейтрален).\n\n"
            "**Распределение электронов по уровням:**\n"
            "• Первый уровень — не более 2 e⁻, второй — не более 8, третий — не более 18 (в 9 классе обычно до 8).\n"
            "• Максимальное число электронов на уровне N определяется формулой 2n².\n\n"
            "**Пример:** углерод C, Z=6 → 6 протонов, 6 электронов. Конфигурация: 2, 4.\n"
            "**Изотопы** — атомы одного элемента с разным числом нейтронов (например, ¹²C и ¹⁴C).\n"
            "**Ионы** образуются при отдаче или принятии электронов: катионы (+), анионы (−)."
        ),
        "questions": [
            {"q": "Сколько протонов в атоме углерода (C)?", "options": ["6", "12", "8", "14"], "correct": 0},
            {"q": "Какой заряд у электрона?", "options": ["положительный", "отрицательный", "нейтральный", "зависит от атома"], "correct": 1},
            {"q": "Что находится в ядре атома?", "options": ["электроны", "протоны и нейтроны", "только протоны", "нейтроны и электроны"], "correct": 1},
            {"q": "Максимальное число электронов на втором уровне:", "options": ["2", "8", "18", "6"], "correct": 1},
            {"q": "Изотопы одного элемента различаются числом:", "options": ["протонов", "электронов", "нейтронов", "позитронов"], "correct": 2},
            {"q": "Атом, потерявший один электрон, становится:", "options": ["анионом", "катионом", "нейтральным", "молекулой"], "correct": 1}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Определите число нейтронов в атоме натрия ²³Na.\n"
                "Решение:\n"
                "1) Массовое число A = 23, порядковый номер Z = 11 (число протонов).\n"
                "2) Число нейтронов N = A – Z = 23 – 11 = 12.\n"
                "Ответ: 12."
            ),
            "formulas": "**Нужные формулы:**\n• N = A – Z\n• Число электронов = число протонов (Z)\n• В ионе: число электронов = Z – заряд (для катиона) или Z + заряд (для аниона)",
            "problems": [
                {
                    "question": "Сколько нейтронов в атоме алюминия ²⁷Al?",
                    "answer": "14",
                    "explanation": "A=27, Z=13 → N = 27-13 = 14."
                },
                {
                    "question": "Определите число электронов в ионе Mg²⁺ (Z=12).",
                    "answer": "10",
                    "explanation": "Атом Mg имеет 12 электронов, потерял 2 → 10."
                }
            ]
        }
    },
    "chemical_bond": {
        "title": "Химическая связь",
        "theory": (
            "🔗 **Химическая связь**\n\n"
            "Химическая связь — взаимодействие атомов, приводящее к образованию устойчивых систем (молекул, кристаллов). Типы связи определяются электроотрицательностью (ЭО) элементов.\n\n"
            "**1. Ионная связь** — образуется между металлом и неметаллом за счёт электростатического притяжения противоположно заряженных ионов. Пример: NaCl (Na⁺ и Cl⁻).\n\n"
            "**2. Ковалентная связь** — связь между атомами неметаллов путём образования общих электронных пар.\n"
            "   • Неполярная — между одинаковыми неметаллами (O₂, H₂, N₂). ЭО одинакова, облако симметрично.\n"
            "   • Полярная — между разными неметаллами (HCl, H₂O). ЭО разная, смещение электронной плотности к более электроотрицательному атому.\n\n"
            "**3. Металлическая связь** — в металлах и сплавах; валентные электроны обобществлены («электронный газ»), что объясняет электропроводность и блеск.\n\n"
            "**Важно:** Водородная связь (слабая) – между молекулами воды, ДНК и т.д."
        ),
        "questions": [
            {"q": "Какая связь в NaCl?", "options": ["ковалентная полярная", "ионная", "ковалентная неполярная", "металлическая"], "correct": 1},
            {"q": "Тип связи в O₂:", "options": ["ионная", "ковалентная полярная", "ковалентная неполярная", "водородная"], "correct": 2},
            {"q": "Ковалентная полярная связь образуется между:", "options": ["одинаковыми неметаллами", "металлом и неметаллом", "разными неметаллами", "металлами"], "correct": 2},
            {"q": "В каком веществе есть ионная связь?", "options": ["H₂O", "MgO", "CO₂", "O₂"], "correct": 1},
            {"q": "Число общих электронных пар в молекуле азота N₂:", "options": ["1", "2", "3", "4"], "correct": 2},
            {"q": "Металлическая связь характерна для:", "options": ["NaCl", "Fe", "HCl", "CaO"], "correct": 1}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Определите тип связи в молекуле HCl.\n"
                "Решение:\n"
                "Электроотрицательность H = 2,1; Cl = 3,0. Разница ЭО = 0,9 – связь ковалентная полярная (разница 0,4–1,7).\n"
                "Ответ: ковалентная полярная."
            ),
            "formulas": "**Ориентиры:**\n• Разница ЭО < 0,4 – ковалентная неполярная\n• 0,4 ≤ разница ЭО ≤ 1,7 – ковалентная полярная\n• разница ЭО > 1,7 – ионная\n• В металлах – металлическая связь.",
            "problems": [
                {
                    "question": "Какая связь образуется между атомами с ЭО = 1,0 и 3,5?",
                    "answer": "ионная",
                    "explanation": "Разница ЭО = 2,5 > 1,7 – ионная связь."
                },
                {
                    "question": "Сколько общих электронных пар в молекуле кислорода O₂?",
                    "answer": "2",
                    "explanation": "Двойная связь (O=O) – две общие пары."
                }
            ]
        }
    },
    "reactions": {
        "title": "Реакции и уравнения",
        "theory": (
            "🧪 **Химические реакции** — превращение одних веществ (реагентов) в другие (продукты).\n\n"
            "**Признаки реакций:** изменение цвета, выпадение осадка, выделение газа, появление запаха, выделение/поглощение тепла.\n\n"
            "**Типы реакций:**\n"
            "• Соединения: A + B → AB (2H₂ + O₂ → 2H₂O)\n"
            "• Разложения: AB → A + B (2H₂O₂ → 2H₂O + O₂)\n"
            "• Замещения: A + BC → AC + B (Zn + 2HCl → ZnCl₂ + H₂)\n"
            "• Обмена: AB + CD → AD + CB (NaOH + HCl → NaCl + H₂O)\n\n"
            "**Тепловой эффект:** экзотермические (+Q, выделение тепла) и эндотермические (-Q, поглощение).\n"
            "**Скорость реакции** зависит от природы веществ, температуры, концентрации, поверхности соприкосновения, катализатора.\n\n"
            "**Закон сохранения массы:** масса веществ до реакции равна массе после (уравнивание коэффициентами)."
        ),
        "questions": [
            {"q": "Сумма коэффициентов в реакции 2H₂ + O₂ → 2H₂O:", "options": ["3", "4", "5", "6"], "correct": 2},
            {"q": "Реакция NaOH + HCl → NaCl + H₂O относится к типу:", "options": ["соединения", "разложения", "замещения", "обмена"], "correct": 3},
            {"q": "Экзотермическая реакция — это реакция, идущая:", "options": ["с поглощением тепла", "без изменения тепла", "с выделением тепла", "только на свету"], "correct": 2},
            {"q": "Какой фактор НЕ влияет на скорость реакции?", "options": ["температура", "давление (для газов)", "цвет посуды", "концентрация"], "correct": 2},
            {"q": "В реакции Zn + 2HCl → ZnCl₂ + H₂ цинк:", "options": ["окисляется", "восстанавливается", "не изменяется", "является окислителем"], "correct": 0},
            {"q": "Какое уравнение соответствует реакции замещения?", "options": ["CaCO₃ → CaO + CO₂", "2Na + 2H₂O → 2NaOH + H₂", "HCl + KOH → KCl + H₂O", "S + O₂ → SO₂"], "correct": 1}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Сколько граммов воды образуется при сгорании 4 г водорода?\n"
                "Уравнение: 2H₂ + O₂ → 2H₂O\n"
                "Решение:\n"
                "1) n(H₂) = m/M = 4 г / 2 г/моль = 2 моль\n"
                "2) по уравнению: из 2 моль H₂ получается 2 моль H₂O → n(H₂O) = 2 моль\n"
                "3) m(H₂O) = n·M = 2 моль · 18 г/моль = 36 г\n"
                "Ответ: 36 г."
            ),
            "formulas": "**Нужные формулы:**\n• n = m/M\n• m = n·M\n• M(H₂) = 2 г/моль, M(H₂O) = 18 г/моль",
            "problems": [
                {
                    "question": "Сколько моль водорода потребуется для реакции с кислородом, чтобы получить 72 г воды?",
                    "answer": "4 моль",
                    "explanation": "n(H₂O)=72/18=4 моль, по уравнению n(H₂)=n(H₂O)=4 моль."
                },
                {
                    "question": "Какая масса оксида кальция образуется при разложении 200 г известняка (CaCO₃), если уравнение: CaCO₃ → CaO + CO₂? (M(CaCO₃)=100 г/моль, M(CaO)=56 г/моль)",
                    "answer": "112 г",
                    "explanation": "n(CaCO₃)=200/100=2 моль, n(CaO)=2 моль, m(CaO)=2·56=112 г."
                }
            ]
        }
    },
    "substance_classes": {
        "title": "Основные классы веществ",
        "theory": (
            "📚 **Основные классы неорганических соединений**\n\n"
            "**1. Оксиды** — бинарные соединения элемента с кислородом (степень окисления O = -2).\n"
            "• Основные оксиды (Na₂O, CaO) — соответствуют основаниям, реагируют с кислотами.\n"
            "• Кислотные оксиды (SO₃, CO₂) — соответствуют кислотам, реагируют со щелочами.\n"
            "• Амфотерные (ZnO, Al₂O₃) — реагируют и с кислотами, и с основаниями.\n\n"
            "**2. Основания** — вещества, диссоциирующие в воде с образованием OH⁻. Состоят из металла и гидроксогрупп. Примеры: NaOH, Ca(OH)₂.\n"
            "• Щёлочи — растворимые основания (KOH, Ba(OH)₂).\n\n"
            "**3. Кислоты** — вещества, диссоциирующие с образованием H⁺. Состоят из водорода и кислотного остатка. HCl, H₂SO₄, HNO₃.\n\n"
            "**4. Соли** — продукты замещения водорода кислоты металлом (NaCl, CaCO₃). Бывают средние, кислые, основные.\n\n"
            "**Генетическая связь:** металл → основный оксид → основание → соль; неметалл → кислотный оксид → кислота → соль."
        ),
        "questions": [
            {"q": "Какой оксид соответствует H₂SO₄?", "options": ["SO₂", "SO₃", "H₂S", "S₂O₃"], "correct": 1},
            {"q": "Формула гидроксида кальция:", "options": ["CaOH", "Ca(OH)₂", "Ca₂OH", "CaO"], "correct": 1},
            {"q": "Какое из веществ является солью?", "options": ["HCl", "NaOH", "NaCl", "H₂O"], "correct": 2},
            {"q": "Амфотерный оксид — это:", "options": ["только основные свойства", "только кислотные", "и основные, и кислотные", "не реагирует"], "correct": 2},
            {"q": "Щёлочь — это:", "options": ["растворимое основание", "нерастворимое основание", "кислота", "соль"], "correct": 0},
            {"q": "Какой ряд состоит только из кислотных оксидов?", "options": ["CO₂, SO₃, P₂O₅", "Na₂O, CaO, MgO", "Al₂O₃, ZnO, BeO", "K₂O, Li₂O, BaO"], "correct": 0}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи на классы веществ:**\n\n"
                "Определите массу соли, которая образуется при взаимодействии 80 г гидроксида натрия (NaOH) с серной кислотой.\n"
                "Уравнение: 2NaOH + H₂SO₄ → Na₂SO₄ + 2H₂O\n"
                "Решение:\n"
                "1) n(NaOH) = m/M = 80 г / 40 г/моль = 2 моль\n"
                "2) по уравнению: из 2 моль NaOH получается 1 моль Na₂SO₄ → n(Na₂SO₄) = 1 моль\n"
                "3) M(Na₂SO₄) = 142 г/моль, m = 1·142 = 142 г\n"
                "Ответ: 142 г."
            ),
            "formulas": "**Нужные формулы:**\n• n = m/M\n• m = n·M\n• M(NaOH) = 40 г/моль, M(Na₂SO₄) = 142 г/моль",
            "problems": [
                {
                    "question": "Сколько граммов соли получится при реакции 4 моль NaOH с избытком H₂SO₄?",
                    "answer": "284 г",
                    "explanation": "n(Na₂SO₄) = 2 моль, m = 2·142 = 284 г."
                },
                {
                    "question": "Какая масса оксида магния потребуется для получения 148 г гидроксида магния Mg(OH)₂ по реакции MgO + H₂O → Mg(OH)₂? (M(MgO)=40 г/моль, M(Mg(OH)₂)=58 г/моль)",
                    "answer": "102 г",
                    "explanation": "n(Mg(OH)₂)=148/58≈2.55 моль, n(MgO)=2.55 моль, m=2.55·40≈102 г."
                }
            ]
        }
    },
    "electrolytic_dissociation": {
        "title": "Электролитическая диссоциация",
        "theory": (
            "💧 **Электролитическая диссоциация** — распад электролита на ионы при растворении или расплавлении.\n\n"
            "**Электролиты** — вещества, растворы/расплавы которых проводят электрический ток (кислоты, основания, соли).\n"
            "**Неэлектролиты** — не проводят ток (органические вещества, газы, сахар).\n\n"
            "**Степень диссоциации α** — отношение числа распавшихся молекул к общему числу.\n"
            "• Сильные электролиты (α > 30%): HCl, NaOH, NaCl, H₂SO₄ (по первой ступени).\n"
            "• Слабые электролиты (α < 3%): H₂CO₃, NH₃·H₂O, уксусная кислота.\n\n"
            "**Ионные уравнения:** реакции обмена записывают в ионном виде, исключая нерастворимые, газообразные и слабодиссоциирующие вещества."
        ),
        "questions": [
            {"q": "Электролитом является:", "options": ["сахар", "спирт", "соляная кислота", "глюкоза"], "correct": 2},
            {"q": "При диссоциации NaCl образуются ионы:", "options": ["Na⁺ и Cl⁻", "Na и Cl₂", "NaOH и HCl", "NaO⁻ и Cl⁺"], "correct": 0},
            {"q": "Сильный электролит:", "options": ["H₂CO₃", "NH₃·H₂O", "NaOH", "CH₃COOH"], "correct": 2},
            {"q": "Степень диссоциации сильных электролитов:", "options": ["близка к 0", "около 50%", "близка к 100%", "всегда 50%"], "correct": 2},
            {"q": "Какое уравнение является ионным для реакции HCl + NaOH?", "options": ["H⁺ + OH⁻ → H₂O", "Na⁺ + Cl⁻ → NaCl", "H₂ + O₂ → H₂O", "NaOH + HCl → NaCl + H₂O"], "correct": 0},
            {"q": "Вещество, не диссоциирующее в воде:", "options": ["KOH", "BaCl₂", "CaCO₃", "HNO₃"], "correct": 2}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Напишите уравнение диссоциации серной кислоты.\n"
                "Решение:\n"
                "H₂SO₄ → 2H⁺ + SO₄²⁻\n"
                "Ответ: H₂SO₄ → 2H⁺ + SO₄²⁻"
            ),
            "formulas": "**Правила:**\n• Сильные электролиты диссоциируют полностью, слабые – частично.\n• Суммарный заряд ионов слева и справа должен быть равен нулю.",
            "problems": [
                {
                    "question": "Сколько ионов образуется при диссоциации одной молекулы AlCl₃?",
                    "answer": "4",
                    "explanation": "AlCl₃ → Al³⁺ + 3Cl⁻ – всего 1+3=4 иона."
                },
                {
                    "question": "Напишите уравнение диссоциации гидроксида калия.",
                    "answer": "KOH → K⁺ + OH⁻",
                    "explanation": "Щёлочь, диссоциирует нацело."
                }
            ]
        }
    },
    "redox": {
        "title": "Окислительно-восстановительные реакции",
        "theory": (
            "🔄 **ОВР** — реакции, в которых изменяются степени окисления элементов.\n\n"
            "**Степень окисления** — условный заряд атома при предположении, что все связи ионные. Правила расчёта: O (-2), H (+1), металлы (+) и т.д.\n\n"
            "• **Окисление** — отдача электронов, степень окисления повышается. Вещество — восстановитель.\n"
            "• **Восстановление** — приём электронов, степень окисления понижается. Вещество — окислитель.\n\n"
            "**Метод электронного баланса** помогает расставить коэффициенты в ОВР."
        ),
        "questions": [
            {"q": "В реакции Zn + 2HCl → ZnCl₂ + H₂ цинк:", "options": ["окисляется", "восстанавливается", "не изменяется", "является окислителем"], "correct": 0},
            {"q": "Степень окисления кислорода в H₂O:", "options": ["-2", "+2", "0", "-1"], "correct": 0},
            {"q": "Окислитель — вещество, которое:", "options": ["отдаёт электроны", "принимает электроны", "не меняет заряд", "содержит водород"], "correct": 1},
            {"q": "В реакции 2Al + 3S → Al₂S₃ сера:", "options": ["окисляется", "восстанавливается", "не меняет степень окисления", "является восстановителем"], "correct": 1},
            {"q": "Сумма всех степеней окисления в молекуле равна:", "options": ["+1", "0", "-1", "заряду иона"], "correct": 1},
            {"q": "Какая реакция является ОВР?", "options": ["NaOH + HCl → NaCl + H₂O", "CaO + CO₂ → CaCO₃", "Fe + CuSO₄ → FeSO₄ + Cu", "AgNO₃ + NaCl → AgCl↓ + NaNO₃"], "correct": 2}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Определите степень окисления серы в SO₃.\n"
                "Решение:\n"
                "Кислород имеет степень окисления -2. Сумма степеней окисления в молекуле равна 0.\n"
                "Обозначим степень окисления серы за x. Тогда x + 3·(-2) = 0 → x = +6.\n"
                "Ответ: +6."
            ),
            "formulas": "**Основные правила:**\n• O: -2 (кроме пероксидов и фторида кислорода)\n• H: +1\n• Металлы IA и IIA групп: +1 и +2 соответственно\n• Сумма степеней окисления в нейтральной молекуле = 0, в ионе равна заряду иона.",
            "problems": [
                {
                    "question": "Чему равна степень окисления азота в HNO₃?",
                    "answer": "+5",
                    "explanation": "H +1, O -2 (три атома = -6). Сумма = 0: +1 + x + (-6) = 0 → x = +5."
                },
                {
                    "question": "В реакции Fe₂O₃ + 3CO → 2Fe + 3CO₂ укажите окислитель.",
                    "answer": "Fe₂O₃",
                    "explanation": "Железо понижает степень окисления с +3 до 0, принимает электроны – окислитель Fe₂O₃."
                }
            ]
        }
    },
    "metals": {
        "title": "Металлы",
        "theory": (
            "🔩 **Металлы** — элементы, обладающие металлической кристаллической решёткой, высокой электро- и теплопроводностью, ковкостью, металлическим блеском.\n\n"
            "**Положение в ПСХЭ:** в левом нижнем углу (IA–IIIA группы, побочные подгруппы).\n\n"
            "**Химические свойства:**\n"
            "• Взаимодействуют с неметаллами (O₂, Cl₂, S) с образованием оксидов, хлоридов, сульфидов.\n"
            "• Реагируют с кислотами (стоящие до водорода в ряду активности вытесняют H₂).\n"
            "• Активные металлы (Li–Na) реагируют с водой при обычных условиях, менее активные (Mg–Fe) — при нагревании.\n\n"
            "**Ряд активности (напряжений):** Li > K > Ba > Ca > Na > Mg > Al > Mn > Zn > Fe > Ni > Sn > Pb > (H) > Cu > Hg > Ag > Au."
        ),
        "questions": [
            {"q": "Самый активный металл из перечисленных:", "options": ["Au", "Fe", "K", "Cu"], "correct": 2},
            {"q": "Металлы в реакциях обычно:", "options": ["принимают электроны", "отдают электроны", "не изменяются", "являются окислителями"], "correct": 1},
            {"q": "При реакции натрия с водой образуется:", "options": ["Na₂O", "NaOH + H₂", "NaH", "NaCl"], "correct": 1},
            {"q": "Какой металл не вытеснит водород из соляной кислоты?", "options": ["Zn", "Fe", "Cu", "Mg"], "correct": 2},
            {"q": "Металлический блеск и электропроводность обусловлены:", "options": ["ионной связью", "обобществлёнными электронами", "ковалентной связью", "водородными связями"], "correct": 1},
            {"q": "Ряд активности металлов начинается с:", "options": ["Cu", "Fe", "Li", "Au"], "correct": 2}
        ],
        "tasks": {
            "example": (
                "✏️ **Пример решения задачи:**\n\n"
                "Какой объём водорода (н.у.) выделится при растворении 6,5 г цинка в соляной кислоте?\n"
                "Уравнение: Zn + 2HCl → ZnCl₂ + H₂↑\n"
                "Решение:\n"
                "1) n(Zn) = m/M = 6,5 г / 65 г/моль = 0,1 моль\n"
                "2) по уравнению n(H₂) = n(Zn) = 0,1 моль\n"
                "3) V(H₂) = n·Vm = 0,1 моль · 22,4 л/моль = 2,24 л\n"
                "Ответ: 2,24 л."
            ),
            "formulas": "**Нужные формулы:**\n• n = m/M\n• V = n·Vm (Vm = 22,4 л/моль при н.у.)\n• M(Zn) = 65 г/моль",
            "problems": [
                {
                    "question": "Какой объём водорода (н.у.) выделится при взаимодействии 2,8 г железа с серной кислотой? (M(Fe)=56 г/моль)",
                    "answer": "1,12 л",
                    "explanation": "n(Fe)=2,8/56=0,05 моль; по уравнению Fe + H₂SO₄ → FeSO₄ + H₂↑ n(H₂)=0,05 моль, V=0,05·22,4=1,12 л."
                },
                {
                    "question": "Какая масса магния потребуется для вытеснения 4,48 л водорода из кислоты? (M(Mg)=24 г/моль)",
                    "answer": "4,8 г",
                    "explanation": "n(H₂)=4,48/22,4=0,2 моль; Mg + 2HCl → MgCl₂ + H₂↑ n(Mg)=0,2 моль, m=0,2·24=4,8 г."
                }
            ]
        }
    }
}

# ---- Клавиатуры ----
def main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Выбрать тему")],
            [KeyboardButton(text="📊 Зачётная книжка")],
            [KeyboardButton(text="📋 План занятий")],
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
    builder.button(text="📋 Выбрать другую тему", callback_data="back_to_topics")
    builder.button(text="📊 Зачётная книжка", callback_data="progress")
    builder.adjust(1)
    return builder.as_markup()

# ---- Команды ----
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🧪 Привет! Я репетитор по химии для 9 класса.\n"
        "Выбери тему, чтобы изучить теорию или пройти тест.",
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
            best = stats["best_percent"]
            attempts = stats["attempts"]
            lines.append(f"✅ {data['title']} — {best:.0f}% ({attempts} поп.)")
        else:
            lines.append(f"⬜ {data['title']} — не пройдена")
    await message.answer("\n".join(lines), reply_markup=topics_inline_kb())

@dp.callback_query(F.data.startswith("select_"))
async def select_topic(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    await state.update_data(current_topic=topic_id)
    topic_title = TOPICS[topic_id]["title"]
    await callback.message.edit_text(
        f"📘 Тема: **{topic_title}**\n\nВыбери действие:",
        reply_markup=topic_actions_kb(topic_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("theory_"))
async def show_theory(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    await callback.message.edit_text(
        TOPICS[topic_id]["theory"],
        reply_markup=after_action_kb(topic_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("test_"))
async def start_test(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    await state.update_data(current_topic=topic_id, question_index=0, correct_count=0)
    q = TOPICS[topic_id]["questions"][0]
    text = f"📝 Тест по теме «{TOPICS[topic_id]['title']}»\n\nВопрос 1:\n{q['q']}"
    await callback.message.answer(text, reply_markup=question_kb(topic_id, 0))
    await callback.message.delete()
    await state.set_state(Quiz.question_index)
    await callback.answer()

@dp.callback_query(F.data.startswith("tasks_"))
async def start_tasks(callback: types.CallbackQuery, state: FSMContext):
    topic_id = callback.data.split("_", 1)[1]
    tasks_data = TOPICS[topic_id].get("tasks")
    if not tasks_data:
        await callback.answer("В этой теме пока нет задач", show_alert=True)
        return
    await state.update_data(current_topic=topic_id, task_index=0, task_correct=0)
    example = tasks_data["example"]
    formulas = tasks_data.get("formulas", "")
    text = f"📝 **Задачи по теме «{TOPICS[topic_id]['title']}»**\n\n{example}\n\n{formulas}"
    await callback.message.edit_text(text, reply_markup=None)
    await callback.message.answer("Теперь решите задачу самостоятельно. Введите ответ.")
    first_problem = tasks_data["problems"][0]
    await callback.message.answer(f"Задача 1:\n{first_problem['question']}")
    await state.set_state(Quiz.task_answer)
    await callback.answer()

@dp.message(Quiz.task_answer)
async def check_task_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    topic_id = data["current_topic"]
    idx = data["task_index"]
    correct = data["task_correct"]
    tasks_data = TOPICS[topic_id]["tasks"]
    problem = tasks_data["problems"][idx]
    user_answer = message.text.strip()
    expected = problem["answer"].strip()
    if user_answer.lower() == expected.lower():
        correct += 1
        await message.answer("✅ Верно!")
    else:
        await message.answer(f"❌ Неверно. Правильный ответ: {expected}\n{problem.get('explanation', '')}")
    idx += 1
    await state.update_data(task_index=idx, task_correct=correct)
    if idx < len(tasks_data["problems"]):
        next_problem = tasks_data["problems"][idx]
        await message.answer(f"Задача {idx+1}:\n{next_problem['question']}")
    else:
        total = len(tasks_data["problems"])
        await message.answer(f"🎉 Вы решили все задачи по теме «{TOPICS[topic_id]['title']}»!\nПравильных ответов: {correct} из {total}")
        await state.set_state(Quiz.main_menu)

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
        next_q = TOPICS[topic_id]["questions"][idx]
        question_text = f"📝 Тест по теме «{TOPICS[topic_id]['title']}»\n\nВопрос {idx+1}:\n{next_q['q']}"
        await callback.message.answer(question_text, reply_markup=question_kb(topic_id, idx))
        await callback.message.delete()
        await callback.answer()
        return
    else:
        total = len(TOPICS[topic_id]["questions"])
        percent = (correct_count / total) * 100
        user_id = callback.from_user.id

        if user_id not in user_progress:
            user_progress[user_id] = {}
        prev = user_progress[user_id].get(topic_id, {"attempts": 0, "best_percent": 0.0})
        new_attempts = prev["attempts"] + 1
        new_best = max(prev["best_percent"], percent)
        user_progress[user_id][topic_id] = {"attempts": new_attempts, "best_percent": new_best}
        save_progress(user_id, topic_id, new_attempts, new_best)

        await callback.message.edit_text(
            f"🎉 Тема пройдена!\n\n{result_text}\n\n"
            f"Правильных ответов: {correct_count} из {total} ({percent:.0f}%)",
            reply_markup=after_action_kb(topic_id)
        )
        await state.set_state(Quiz.main_menu)
        await callback.answer()

@dp.callback_query(F.data == "back_to_topics")
async def back_to_topics(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📚 Доступные темы:", reply_markup=topics_inline_kb())
    await callback.answer()

@dp.callback_query(F.data == "progress")
async def progress_inline(callback: types.CallbackQuery):
    await show_progress(callback.from_user.id, callback.message)
    await callback.answer()

@dp.message(Command("progress"))
async def cmd_progress(message: types.Message):
    await show_progress(message.from_user.id, message)

async def show_progress(user_id: int, target):
    if user_id not in user_progress or not user_progress[user_id]:
        text = "📊 Зачётная книжка пуста. Пройди хотя бы один тест!"
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

@dp.message()
async def echo(message: types.Message, state: FSMContext):
    await message.answer("Для начала нажми /start", reply_markup=main_menu_kb())

# ---- Запуск ----
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