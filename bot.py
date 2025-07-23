#bot

import html
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
import asyncio
import re

from datetime import datetime
from dateutil.relativedelta import relativedelta

from app.logger import logger
from app.sheets import *
from config import *

# Инициализация бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Состояния пользователей
user_states = {}


async def answer_callback(callback: types.CallbackQuery, text: str):
    try:
        await callback.answer(text)
    except Exception as e:
        logger.warning(f"Не удалось ответить на callback: {e}")



from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Добавляем в начало файла
MONTH_BUTTONS = [
    [KeyboardButton(text="Текущий месяц"), KeyboardButton(text="Следующий месяц")],
    [KeyboardButton(text="Данные (клавиатура)")]
]

# Обновляем функцию start
@dp.message(Command("start"))
async def start(message: types.Message):
    # Отправляем приветственное сообщение с инлайн-клавиатурой
    await message.answer(
        "Добро пожаловать! Выберите действие:",
        reply_markup=get_month_keyboard()  # Инлайн-клавиатура
    )
    
    # Отправляем второе сообщение с обычной клавиатурой
    await message.answer(
        "Или используйте кнопки ниже:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=MONTH_BUTTONS,
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

# В bot.py добавим новый обработчик

@dp.message(F.text.startswith("Отмена"))
async def handle_cancel_command(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in user_states or 'current_month' not in user_states[user_id]:
        await message.answer("Сначала выберите месяц с помощью команды /start")
        return
    
    try:
        lines = [line.strip() for line in message.text.split('\n') if line.strip()]
        
        if len(lines) < 2:
            raise ValueError("Сообщение отмены должно содержать минимум 2 строки")
        
        # Парсим данные
        if lines[0].lower() != "отмена":
            raise ValueError("Первая строка должна быть 'Отмена'")
        
        day = int(lines[1])
        channels_data = []
        
        for data in lines[2:]:
            parts = data.rsplit(' ', 1)
            if len(parts) != 2:
                raise ValueError(f"Неверный формат: {data}")
            
            channel_name = parts[0].strip()
            time_str = parts[1]
            
            # Проверка формата времени
            if not re.match(r'^\d{1,2}:\d{2}$', time_str):
                raise ValueError(f"Неверный формат времени: {time_str}")
            
            channels_data.append({
                'channel': channel_name,
                'time': time_str
            })
        
        # Проверяем валидность данных
        if day < 1 or day > 31:
            raise ValueError("День должен быть числом от 1 до 31")
        
        current_month = user_states[user_id]['current_month']
        client = await setup_google_sheets()
        
        # Получаем отчет об отмене
        report = await cancel_table_cells(
            client, 
            current_month, 
            day, 
            channels_data
        )
        
        # После обработки предлагаем выбрать месяц снова
        user_states[user_id].pop('current_month', None)
        await message.answer(
            f"{report}\n\nВыберите месяц для следующей операции:",
            reply_markup=get_month_keyboard(),
            parse_mode="HTML"
        )
    
    except Exception as e:
        logger.error(f"Ошибка обработки отмены: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуйте отправить отмену снова или начните заново с /start")

# Обработчик для обычной клавиатуры
@dp.message(F.text.in_(["Текущий месяц", "Следующий месяц", "Данные (клавиатура)"]))
async def handle_keyboard(message: types.Message):
    if message.text == "Данные (клавиатура)":
        await view_data_handler_keyboard(message)
    else:
        today = datetime.now()
        target_date = today if message.text == "Текущий месяц" else today + relativedelta(months=1)
        
        client = await setup_google_sheets()
        await ensure_sheet_exists(client, target_date)
        
        user_states[message.from_user.id] = {
            'current_month': target_date
        }
        
        await message.answer(
            f"✅ Лист для {MONTH_NAMES[target_date.month]} {target_date.year} готов!\n\n"
            "Теперь отправьте данные для заполнения в формате:\n\n"
            "<b>Для добавления записи:</b>\n"
            "<b>Текст сообщения</b>\n"
            "<b>Число (день месяца)</b>\n"
            "<b>Цвет (красный/желтый/розовый/голубой)</b>\n"
            "<b>Канал 1 9:05</b>\n"
            "<b>Канал 2 10:30</b>\n\n"
            "Пример добавления:\n"
            "<code>Экстренный выпуск новостей\n"
            "15\n"
            "голубой\n"
            "МАСТЕРСКАЯ 9:05\n"
            "Канал 2 10:30</code>\n\n"
            "Пример отмены:\n"
            "<code>Отмена\n"
            "15\n"
            "МАСТЕРСКАЯ 9:05\n"
            "Канал 2 10:30</code>\n\n",
            parse_mode="HTML"
        )

# Новая версия обработчика для кнопки "Данные" (инлайн)
@dp.callback_query(F.data == "view_data")
async def view_data_handler(callback: types.CallbackQuery):
    await answer_callback(callback, "Просмотр данных")
    await callback.message.answer(  # Отправляем новое сообщение
        "Выберите месяц для просмотра данных:",
        reply_markup=get_data_keyboard()
    )

# Обработчик для кнопки "Данные" (обычная клавиатура)
async def view_data_handler_keyboard(message: types.Message):
    await message.answer(
        "Выберите месяц для просмотра данных:",
        reply_markup=get_data_keyboard()
    )

# Обновляем функцию get_data_keyboard
def get_data_keyboard(target_date=None):
    builder = InlineKeyboardBuilder()
    
    # Кнопки месяцев
    today = datetime.now()
    for i in range(3):
        month_date = today + relativedelta(months=i)
        builder.add(InlineKeyboardButton(
            text=f"{MONTH_NAMES[month_date.month]} {month_date.year}",
            callback_data=f"data_month_{month_date.month}_{month_date.year}"
        ))
    
    # Кнопки дней (31 кнопка)
    if target_date:
        for day in range(1, 32):
            builder.add(InlineKeyboardButton(
                text=str(day),
                callback_data=f"data_day_{target_date.month}_{target_date.year}_{day}"
            ))
    
    builder.adjust(3, *[7]*5)  # 3 месяца, затем по 7 дней в строке
    return builder.as_markup()


@dp.message(Command("cancel"))
async def cancel_command(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        await message.answer("Текущая операция отменена. Выберите месяц снова.")
    else:
        await message.answer("Нет активных операций для отмены.")
    await start(message)


# В обработчике callback_query
@dp.callback_query(F.data.startswith("data_month_"))
async def process_data_month_selection(callback: types.CallbackQuery):
    try:
        await answer_callback(callback, "Выбор месяца для просмотра")
        
        _, _, month, year = callback.data.split('_')
        target_date = datetime(int(year), int(month), 1)
        
        # Сохраняем выбранный месяц для пользователя
        user_states[callback.from_user.id] = {
            'mode': 'data_view',
            'target_month': target_date
        }
        
        await callback.message.edit_text(
            f"Выберите день в {MONTH_NAMES[target_date.month]} {target_date.year}:",
            reply_markup=get_data_keyboard(target_date)
        )
            
    except Exception as e:
        logger.error(f"Ошибка в process_data_month_selection: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")

@dp.callback_query(F.data.startswith("data_day_"))
async def process_data_day_selection(callback: types.CallbackQuery):
    try:
        await answer_callback(callback, "Загрузка данных...")
        
        _, _, month, year, day = callback.data.split('_')
        target_date = datetime(int(year), int(month), int(day))
        user_id = callback.from_user.id
        
        if user_id not in user_states or 'target_month' not in user_states[user_id]:
            await callback.message.answer("Сессия устарела. Начните заново с /start")
            return
        
        # Получаем данные из таблицы
        client = await setup_google_sheets()
        report = await get_day_data(client, target_date)
        
        # Разрешаем HTML-разметку в сообщении
        await callback.message.edit_text(
            f"Данные за {day}.{month}.{year}:\n\n{report}\n\nВыберите другую дату:",
            reply_markup=get_data_keyboard(user_states[user_id]['target_month']),
            parse_mode="HTML"  # Добавляем поддержку HTML
        )
        
            
    except Exception as e:
        logger.error(f"Ошибка в process_data_day_selection: {e}")
        await callback.message.answer(f"❌ Ошибка: {str(e)}")


async def get_day_data(client, target_date):
    try:
        sheet_name = get_sheet_name(target_date)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(sheet_name)
        
        report_lines = []
        
        # Читаем все данные листа одним запросом
        try:
            all_data = sheet.get_all_values()
        except Exception as e:
            logger.error(f"Ошибка чтения данных: {e}")
            return f"Ошибка при получении данных: {str(e)}"
        
        # Получаем конфигурацию таблицы
        table_config = TABLE_CONFIG
        table_height = table_config['table_height']
        table_width = table_config['table_width']
        v_spacing = table_config['v_spacing']
        h_spacing = table_config['h_spacing']
        tables_per_row = table_config['tables_per_row']
        
        for channel_idx, channel_name in enumerate(CHANNELS):
            # Определяем положение таблицы канала
            row_idx = channel_idx // tables_per_row
            col_idx = channel_idx % tables_per_row
            
            # Рассчитываем начальную позицию таблицы
            start_row = 1 + row_idx * (table_height + v_spacing)
            start_col = 1 + col_idx * (table_width + h_spacing)
            
            # Рассчитываем позицию дня в таблице
            day_row = start_row + 1 + target_date.day
            
            # Проверяем границы данных
            if day_row - 1 >= len(all_data):
                continue
            
            row_data = all_data[day_row - 1]
            
            # Проверяем состояние слотов
            slots = []
            slot_status = {}
            
            # Времена смен и соответствующие колонки
            shifts = [
                ("9", start_col + 2),   # Утро (№1)
                ("12", start_col + 3),  # Полдень (№2)
                ("15", start_col + 4),  # День (№3)
                ("18", start_col + 5)   # Вечер (№4)
            ]
            
            # Проверяем занятость слотов
            for time, col in shifts:
                if col - 1 < len(row_data):
                    cell_value = row_data[col - 1]
                    # Проверяем, заполнена ли ячейка
                    is_free = not (cell_value and cell_value.strip())
                    slot_status[time] = is_free
                else:
                    slot_status[time] = False  # Считаем занятым, если ячейка за пределами данных
            

            # Формируем строку для канала
            channel_line = []
            free_slots_count = 0
        
            # Формируем строку для канала с возможной ссылкой
            channel_link = CHANNELS_DICT.get(channel_name)
            if channel_link:
                # Экранируем название для безопасного использования в HTML
                escaped_name = html.escape(channel_name)
                channel_line = [f'<a href="{channel_link}">{escaped_name}</a>']
            else:
                channel_line = [channel_name]
            
            # Обрабатываем слоты 9, 12, 15
            for time in ["9", "12", "15"]:
                if slot_status[time]:
                    channel_line.append(time)
                    free_slots_count += 1
            
            if slot_status["18"]:
                free_slots_count += 1

            free_slots_count -= 1

            # Добавляем кружки для свободных слотов (только для 9,12,15)
            if free_slots_count > 0:
                channel_line.append("⭕️" * free_slots_count)
            
            # Обрабатываем слот 18 отдельно
            if slot_status["18"]:
                channel_line.append("18")
            
            # Если есть хотя бы один свободный слот (9,12,15 или 18), добавляем канал в отчет
            if len(channel_line) > 1:
                report_lines.append(" ".join(channel_line))
        
        return format_report(report_lines)
        
    except Exception as e:
        logger.error(f"Ошибка при получении данных: {e}")
        return f"Ошибка при получении данных: {str(e)}"
    

def format_report(channel_data):
    if not channel_data:
        return "Все каналы заняты"
    
    print(channel_data)
    
    lines = []
    for group in CHANNEL_GROUPS:
        group_lines = []
        for channel_idx in group:
            # if channel_idx in channel_data:
            print(channel_idx, len(channel_data))
            group_lines.append(channel_data[channel_idx])
        
        if group_lines:
            lines.extend(group_lines)
            lines.append("")  # Добавляем пустую строку между группами

    # Убираем последнюю пустую строку
    if lines and lines[-1] == "":
        lines.pop()
        
    return "\n".join(lines)


def get_month_keyboard():
    builder = InlineKeyboardBuilder()
    today = datetime.now()
    
    for i in range(3):
        month_date = today + relativedelta(months=i)
        builder.add(InlineKeyboardButton(
            text=f"{MONTH_NAMES[month_date.month]} {month_date.year}",
            callback_data=f"month_{month_date.month}_{month_date.year}"
        ))
    
    # Добавляем кнопку "Данные"
    builder.add(InlineKeyboardButton(
        text="📊 Данные",
        callback_data="view_data"
    ))
    
    builder.adjust(3, 1)
    return builder.as_markup()

# Обработчик для кнопки "Данные"
@dp.callback_query(F.data == "view_data")
async def view_data_handler(callback: types.CallbackQuery):
    await answer_callback(callback, "Просмотр данных")
    await callback.message.edit_text(
        "Выберите месяц для просмотра данных:",
        reply_markup=get_data_keyboard()
    )


@dp.callback_query(F.data.startswith("month_"))
async def process_month_selection(callback: types.CallbackQuery):
    try:
        await answer_callback(callback, "Обработка запроса...")
        
        _, month, year = callback.data.split('_')
        target_date = datetime(int(year), int(month), 1)
        
        client = await setup_google_sheets()
        await ensure_sheet_exists(client, target_date)
        
        # Сохраняем выбранный месяц для пользователя
        user_states[callback.from_user.id] = {
            'current_month': target_date
        }
        
        await callback.message.answer(
            f"✅ Лист для {MONTH_NAMES[target_date.month]} {target_date.year} готов!\n\n"
            "Теперь отправьте данные для заполнения в формате:\n\n"
            "<b>Для добавления записи:</b>\n"
            "<b>Текст сообщения</b>\n"
            "<b>Число (день месяца)</b>\n"
            "<b>Цвет (красный/желтый/розовый/голубой)</b>\n"
            "<b>Канал 1 9:05</b>\n"
            "<b>Канал 2 10:30</b>\n\n"
            "Пример добавления:\n"
            "<code>Экстренный выпуск новостей\n"
            "15\n"
            "голубой\n"
            "МАСТЕРСКАЯ 9:05\n"
            "Канал 2 10:30</code>\n\n",
            parse_mode="HTML"
        )
            
    except Exception as e:
        logger.error(f"Ошибка в process_month_selection: {e}")
        try:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
        except Exception as e2:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")


# В разделе bot.py

@dp.message()
async def handle_data_input(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in user_states or 'current_month' not in user_states[user_id]:
        await message.answer("Сначала выберите месяц с помощью команды /start")
        return
    
    try:
        lines = [line.strip() for line in message.text.split('\n') if line.strip()]
        
        if len(lines) < 4:
            raise ValueError("Сообщение должно содержать минимум 4 строки")
        
        # Парсим данные
        text = lines[0]
        day = int(lines[1])
        color = lines[2].lower()
        channels_data = []
        
        for data in lines[3:]:
            parts = data.rsplit(' ', 1)
            if len(parts) != 2:
                raise ValueError(f"Неверный формат: {data}")
            
            channel_name = parts[0].strip()
            time_str = parts[1]
            
            # Проверка формата времени
            if not re.match(r'^\d{1,2}:\d{2}$', time_str):
                raise ValueError(f"Неверный формат времени: {time_str}")
            
            channels_data.append({
                'channel': channel_name,
                'time': time_str
            })
        
        # Проверяем валидность данных
        if day < 1 or day > 31:
            raise ValueError("День должен быть числом от 1 до 31")
        
        valid_colors = ["красный", "желтый", "розовый", "голубой"]
        if color not in valid_colors:
            raise ValueError(f"Недопустимый цвет. Используйте: {', '.join(valid_colors)}")
        
        current_month = user_states[user_id]['current_month']
        client = await setup_google_sheets()
        
        # Получаем отчет об обновлении
        report = await update_table_cells(
            client, 
            current_month, 
            day, 
            color, 
            text, 
            channels_data
        )
        
        # После обработки предлагаем выбрать месяц снова
        user_states[user_id].pop('current_month', None)
        await message.answer(
            f"{report}\n\nВыберите месяц для следующей операции:",
            reply_markup=get_month_keyboard(),
            parse_mode="HTML"
        )
    
    except Exception as e:
        logger.error(f"Ошибка обработки данных: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуйте отправить данные снова или начните заново с /start")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())