#bot

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


def get_month_keyboard():
    builder = InlineKeyboardBuilder()
    today = datetime.now()
    
    for i in range(3):
        month_date = today + relativedelta(months=i)
        builder.add(InlineKeyboardButton(
            text=f"{MONTH_NAMES[month_date.month]} {month_date.year}",
            callback_data=f"month_{month_date.month}_{month_date.year}"
        ))
    
    builder.adjust(3)
    return builder.as_markup()


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Выберите месяц для управления таблицами:",
        reply_markup=get_month_keyboard()
    )


@dp.message(Command("cancel"))
async def cancel_command(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
        await message.answer("Текущая операция отменена. Выберите месяц снова.")
    else:
        await message.answer("Нет активных операций для отмены.")
    await start(message)


def get_month_keyboard():
    builder = InlineKeyboardBuilder()
    today = datetime.now()
    
    # Всегда показываем 3 месяца: текущий + следующие два
    for i in range(3):
        month_date = today + relativedelta(months=i)
        builder.add(InlineKeyboardButton(
            text=f"{MONTH_NAMES[month_date.month]} {month_date.year}",
            callback_data=f"month_{month_date.month}_{month_date.year}"
        ))
    
    builder.adjust(3)
    return builder.as_markup()


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
            "<b>Текст сообщения</b>\n"
            "<b>Число (день месяца)</b>\n"
            "<b>Цвет (красный/зеленый/желтый/розовый/голубой)</b>\n"
            "<b>Канал 1 9:05</b>\n"
            "<b>Канал 2 10:30</b>\n\n"
            "Пример:\n"
            "Экстренный выпуск новостей\n"
            "15\n"
            "голубой\n"
            "МАСТЕРСКАЯ 9:05\n"
            "Канал 2 10:30",
            parse_mode="HTML"
        )
            
    except Exception as e:
        logger.error(f"Ошибка в process_month_selection: {e}")
        try:
            await callback.message.answer(f"❌ Ошибка: {str(e)}")
        except Exception as e2:
            logger.error(f"Не удалось отправить сообщение об ошибке: {e2}")


@dp.message()
async def handle_data_input(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in user_states or 'current_month' not in user_states[user_id]:
        await message.answer("Сначала выберите месяц с помощью команды /start")
        return
    
    try:
        lines = message.text.split('\n')
        if len(lines) < 4:
            raise ValueError("Сообщение должно содержать минимум 4 строки")
        
        # Парсим данные
        text = lines[0].strip()
        day = int(lines[1].strip())
        color = lines[2].strip().lower()
        channels_data = [line.strip() for line in lines[3:] if line.strip()]
        
        # Проверяем валидность данных
        if day < 1 or day > 31:
            raise ValueError("День должен быть числом от 1 до 31")
        
        valid_colors = ["красный", "зеленый", "желтый", "розовый", "голубой"]
        if color not in valid_colors:
            raise ValueError(f"Недопустимый цвет. Используйте: {', '.join(valid_colors)}")
        
        # Парсим данные каналов
        parsed_channels = []
        for data in channels_data:
            parts = data.rsplit(' ', 1)
            if len(parts) != 2:
                raise ValueError(f"Неверный формат: {data}")
            
            channel_name = parts[0].strip()
            time_str = parts[1]
            
            try:
                time_parts = time_str.split(':')
                if len(time_parts) != 2:
                    raise ValueError
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                if not (0 <= hours < 24 and 0 <= minutes < 60):
                    raise ValueError
            except (ValueError, IndexError):
                raise ValueError(f"Неверный формат времени: {time_str}")
            
            parsed_channels.append({
                'channel': channel_name,
                'time': time_str
            })
        
        current_month = user_states[user_id]['current_month']
        client = await setup_google_sheets()
        
        # Получаем отчет об обновлении
        report = await update_table_cells(
            client, 
            current_month, 
            day, 
            color, 
            text, 
            parsed_channels
        )
        
        # После обработки предлагаем выбрать месяц снова
        user_states[user_id].pop('current_month', None)
        await message.answer(
            f"{report}\n\nВыберите месяц для следующей операции:",
            reply_markup=get_month_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка обработки данных: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуйте отправить данные снова или начните заново с /start")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())