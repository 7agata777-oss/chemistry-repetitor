=== ПРОЕКТ: РЕПЕТИТОР ПО ХИМИИ (9 класс) ===

Репозиторий GitHub:
https://github.com/7agata777-oss/chemistry-repetitor

Сервис Render:
https://dashboard.render.com → chemistry-repetitor

Переменные окружения на Render (указаны как есть):
BOT_TOKEN = (токен бота @Chemistry9RepetitorBot)
PYTHON_VERSION = 3.12.10

Файлы в репозитории:
chemistry_bot.py — основной код бота
requirements.txt — зависимости (aiogram, aiohttp, PyPDF2)
runtime.txt — версия Python (python-3.12.10)
chemistry_textbook.txt — конвертированный текст учебника

ID администратора (Марина): ________
ID дочери (Эльза): ________

Логика:
- Поиск по учебнику через chemistry_textbook.txt
- Защита от стоп-слов и знаков препинания
- Доступ ограничен белым списком (allowed_ids)
- Управление доступом: /add_user, /remove_user, /allowed (только для администратора)

Текущий статус:
Бот полностью работает.
Планируемые доработки: временные подписки, оплата.
