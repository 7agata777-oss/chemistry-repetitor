# Новый стартовый файл бота
import os
from pathlib import Path
from database import SessionLocal, User, Topic, UserProgress, Attempt
import chemistry_bot  # твой старый код

# Загрузка справочников
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

# Загружаем при старте
load_reference_books('data')

# Запускаем старого бота (если там есть executor.start_polling, он сработает)
