#sheets

import logging
from datetime import datetime
from google.api_core import retry
from googleapiclient.errors import HttpError
from dateutil.relativedelta import relativedelta
import gspread
from google.oauth2.service_account import Credentials
import asyncio
import re
import os
import html

from config import *

logger = logging.getLogger(__name__)


# Подключение к Google Sheets
async def setup_google_sheets():
    try:
        if not os.path.exists(CREDS_FILE):
            raise FileNotFoundError(f"Файл {CREDS_FILE} не найден!")
        
        creds = Credentials.from_service_account_file(
            CREDS_FILE, 
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(creds)
        logger.info(f"Используем сервисный аккаунт: {creds.service_account_email}")
        return client
    except Exception as e:
        logger.error(f"Ошибка Google Sheets: {e}")
        raise



def create_sheet_structure(sheet, channels, target_date):
    try:
        # Очищаем лист одним запросом
        sheet.clear()
        
        # Рассчитываем необходимое количество колонок
        required_cols = (TABLE_CONFIG['table_width'] + TABLE_CONFIG['h_spacing']) * TABLE_CONFIG['tables_per_row']
        if sheet.col_count < required_cols:
            sheet.resize(cols=required_cols)
        
        # Подготовим все запросы сразу
        requests = []
        
        for idx, channel in enumerate(channels):
            row_idx = idx // TABLE_CONFIG['tables_per_row']
            col_idx = idx % TABLE_CONFIG['tables_per_row']
            
            start_row = 1 + row_idx * (TABLE_CONFIG['table_height'] + TABLE_CONFIG['v_spacing'])
            start_col = 1 + col_idx * (TABLE_CONFIG['table_width'] + TABLE_CONFIG['h_spacing'])
            
            # Название канала (объединенные ячейки + форматирование)
            requests.extend([
                {
                    'mergeCells': {
                        'range': {
                            'sheetId': sheet.id,
                            'startRowIndex': start_row - 1,
                            'endRowIndex': start_row,
                            'startColumnIndex': start_col - 1,
                            'endColumnIndex': start_col + TABLE_CONFIG['table_width'] - 1
                        },
                        'mergeType': 'MERGE_ALL'
                    }
                },
                {
                    'updateCells': {
                        'range': {
                            'sheetId': sheet.id,
                            'startRowIndex': start_row - 1,
                            'endRowIndex': start_row,
                            'startColumnIndex': start_col - 1,
                            'endColumnIndex': start_col + TABLE_CONFIG['table_width'] - 1
                        },
                        'rows': [{
                            'values': [{
                                'userEnteredValue': {'stringValue': channel.upper()},
                                'userEnteredFormat': {
                                    'horizontalAlignment': 'CENTER',
                                    'textFormat': {'bold': True}
                                }
                            }]
                        }],
                        'fields': 'userEnteredValue,userEnteredFormat'
                    }
                }
            ])
            
            # Добавляем дни и форматирование
            add_table_data(requests, sheet.id, start_row, start_col, target_date)
        
        # Отправляем запросы с ретраями
        execute_requests_with_retry(sheet, requests)
        
    except Exception as e:
        logger.error(f"Ошибка при создании структуры: {e}")
        raise

def add_table_data(requests, sheet_id, start_row, start_col, target_date):
    """Добавляет данные таблицы в общий список запросов"""
    # Заголовки столбцов
    headers = ["День", "Дата", "№1 (утро)", "№2 (полдень)", "№3 (день)", "№4 (вечер)"]
    requests.append({
        'updateCells': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': start_row,
                'endRowIndex': start_row + 1,
                'startColumnIndex': start_col - 1,
                'endColumnIndex': start_col + len(headers) - 1
            },
            'rows': [{
                'values': [{
                    'userEnteredValue': {'stringValue': header},
                    'userEnteredFormat': {
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER'
                    }
                } for header in headers]
            }],
            'fields': 'userEnteredValue,userEnteredFormat'
        }
    })
    
    # Форматирование колонок
    requests.extend([
        {
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': start_row,
                    'endRowIndex': start_row + 32,
                    'startColumnIndex': start_col - 1,
                    'endColumnIndex': start_col
                },
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': COLORS['dark_gray'],
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER'
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'
            }
        },
        {
            'repeatCell': {
                'range': {
                    'sheetId': sheet_id,
                    'startRowIndex': start_row,
                    'endRowIndex': start_row + 32,
                    'startColumnIndex': start_col,
                    'endColumnIndex': start_col + 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'backgroundColor': COLORS['light_gray'],
                        'horizontalAlignment': 'CENTER'
                    }
                },
                'fields': 'userEnteredFormat(backgroundColor,horizontalAlignment)'
            }
        }
    ])
    
    # Заполнение дней
    days_data = []
    for day in range(1, 32):
        try:
            date = datetime(target_date.year, target_date.month, day)
            weekday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][date.weekday()]
            date_str = date.strftime("%d.%m.%y")
            days_data.append((weekday, date_str))
        except ValueError:
            continue
    
    # Добавляем данные дней одним запросом
    rows = []
    for day, (weekday, date_str) in enumerate(days_data, 1):
        rows.append({
            'values': [
                {'userEnteredValue': {'stringValue': weekday}},
                {'userEnteredValue': {'stringValue': date_str}},
                {}, {}, {}, {}  # Пустые значения для смен
            ]
        })
    
    requests.append({
        'updateCells': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': start_row + 1,
                'endRowIndex': start_row + 1 + len(days_data),
                'startColumnIndex': start_col - 1,
                'endColumnIndex': start_col + TABLE_CONFIG['table_width'] - 1
            },
            'rows': rows,
            'fields': 'userEnteredValue'
        }
    })

@retry.Retry(
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    predicate=retry.if_exception_type(HttpError),
)
def execute_requests_with_retry(sheet, requests):
    """Выполняет запросы с повторными попытками"""
    try:
        # Разбиваем запросы на пакеты по 50 (ограничение API)
        for i in range(0, len(requests), 50):
            batch = requests[i:i + 50]
            sheet.spreadsheet.batch_update({'requests': batch})
    except HttpError as e:
        logger.warning(f"Ошибка API (будет повторная попытка): {e}")
        raise
    except Exception as e:
        logger.error(f"Неизвестная ошибка при выполнении запросов: {e}")
        raise

async def ensure_sheet_exists(client, target_date):
    try:
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        base_sheet_name = get_sheet_name(target_date)
        
        # Проверяем существование листа без конфликтного суффикса
        try:
            # Ищем лист по базовому имени
            sheet = spreadsheet.worksheet(base_sheet_name)
            logger.info(f"Лист {base_sheet_name} уже существует")
            return sheet
        except gspread.exceptions.WorksheetNotFound:
            pass
        
        # Проверяем существование листов с конфликтными именами
        all_sheets = spreadsheet.worksheets()
        pattern = re.compile(rf"^{re.escape(base_sheet_name)}_conflict\d+$")
        
        for sheet in all_sheets:
            if pattern.match(sheet.title):
                logger.info(f"Найден конфликтный лист: {sheet.title}")
                # Переименовываем конфликтный лист в правильное имя
                try:
                    sheet.update_title(base_sheet_name)
                    logger.info(f"Лист переименован в {base_sheet_name}")
                    return sheet
                except Exception as e:
                    logger.error(f"Ошибка при переименовании листа: {e}")
        
        # Если не нашли ни базового, ни конфликтного листа - создаем новый
        try:
            sheet = spreadsheet.add_worksheet(title=base_sheet_name, rows=1000, cols=100)
            logger.info(f"Создан новый лист: {base_sheet_name}")
            create_sheet_structure(sheet, CHANNELS, target_date)
            return sheet
        except Exception as e:
            logger.error(f"Ошибка при создании листа: {e}")
            raise

    except Exception as e:
        logger.error(f"Ошибка при работе с листом: {e}")
        raise

def process_existing_sheets(spreadsheet, sheets, months_to_keep):
    """Обрабатывает существующие листы (удаляет старые)"""
    pattern = re.compile(r'^(' + '|'.join(MONTH_NAMES.values()) + r')\d{4}$')
    for sheet in sheets:
        if pattern.match(sheet.title):
            sheet_year = int(sheet.title[-4:])
            sheet_month = next((k for k, v in MONTH_NAMES.items() if v == sheet.title[:-4]), None)
            
            if sheet_month is None:
                continue
                
            sheet_date = datetime(sheet_year, sheet_month, 1)
            
            if not any(sheet_date.year == d.year and sheet_date.month == d.month for d in months_to_keep):
                try:
                    spreadsheet.del_worksheet(sheet)
                    logger.info(f"Удален лист: {sheet.title}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении листа {sheet.title}: {e}")

def get_or_create_sheet(spreadsheet, sheet_name):
    """Получает или создает лист с указанным именем"""
    try:
        # Пытаемся получить существующий лист
        sheet = spreadsheet.worksheet(sheet_name)
        logger.info(f"Лист {sheet_name} уже существует")
        return sheet
    except gspread.exceptions.WorksheetNotFound:
        try:
            sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=100)
            logger.info(f"Создан новый лист: {sheet_name}")
            return sheet
        except Exception as e:
            logger.error(f"Ошибка при создании листа {sheet_name}: {e}")
            raise

def get_sheet_name(date):
    """Генерирует название листа на основе даты"""
    return f"{MONTH_NAMES[date.month]}{date.year}"


async def update_table_cells(client, target_date, day, color_name, text, channels_data):
    try:
        sheet_name = get_sheet_name(target_date)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = get_or_create_sheet(spreadsheet, sheet_name)
        
        # Цвета
        colors = {
            "красный": {"red": 1, "green": 0, "blue": 0},
            "желтый": {"red": 1, "green": 1, "blue": 0},
            "розовый": {"red": 1, "green": 0, "blue": 1},
            "голубой": {"red": 0, "green": 1, "blue": 1},
            "зеленый": {"red": 0, "green": 1, "blue": 0}
        }
        color = colors.get(color_name, {"red": 1, "green": 1, "blue": 1})
        
        # Определяем смену по времени
        def get_shift(time_str):
            try:
                hours = int(time_str.split(':')[0])
                if 6 <= hours < 12: return 'morning'
                elif 12 <= hours < 15: return 'afternoon'
                elif 15 <= hours < 18: return 'day'
                else: return 'evening'
            except: return 'evening'
        
        # Для сбора результатов
        report_data = []
        requests = []
        
        # Собираем все ячейки для чтения
        read_cells = {}
        
        for data in channels_data:
            channel_name = data['channel']
            time_str = data['time']
            shift = get_shift(time_str)
            entry = {
                "channel": channel_name,
                "time": time_str,
                "status": None,
                "message": ""
            }
            
            # Проверяем наличие времени
            if not time_str or time_str.strip() == "":
                entry["status"] = "error"
                entry["message"] = "Не указано время для канала"
                report_data.append(entry)
                continue
            
            try:
                channel_idx = CHANNELS.index(channel_name)
            except ValueError:
                entry["status"] = "error"
                entry["message"] = f"Канал '{channel_name}' не найден"
                report_data.append(entry)
                continue
            
            # Определяем положение таблицы
            tables_per_row = TABLE_CONFIG['tables_per_row']
            row_idx = channel_idx // tables_per_row
            col_idx = channel_idx % tables_per_row
            
            table_config = TABLE_CONFIG
            start_row = 2 + row_idx * (table_config['table_height'] + table_config['v_spacing'])
            start_col = 1 + col_idx * (table_config['table_width'] + table_config['h_spacing'])
            
            # Определяем строку дня
            row = start_row + day
            
            # Определяем колонку для смены
            shift_columns = {
                'morning': 2, 'afternoon': 3, 'day': 4, 'evening': 5
            }
            col = start_col + shift_columns.get(shift, 5)
            
            # Сохраняем для batch-чтения
            key = (row, col)
            if key not in read_cells:
                read_cells[key] = []
            read_cells[key].append({
                'entry': entry,
                'channel_name': channel_name,
                'time_str': time_str
            })
        
        # Читаем все ячейки одним запросом
        cell_values = {}
        if read_cells:
            try:
                # Получаем список всех ячеек для чтения
                cell_list = sheet.range(
                    f"A1:{gspread.utils.rowcol_to_a1(max(row for row, _ in read_cells.keys()), max(col for _, col in read_cells.keys()))}"
                )
                
                # Создаем словарь значений по координатам
                for cell in cell_list:
                    cell_values[(cell.row, cell.col)] = cell.value
                    
            except Exception as e:
                logger.error(f"Ошибка чтения ячеек: {e}")
                for key, items in read_cells.items():
                    for item in items:
                        item['entry']['status'] = "error"
                        item['entry']['message'] = "Ошибка чтения ячейки"
                        report_data.append(item['entry'])
        
        # Обрабатываем ячейки
        for (row, col), items in read_cells.items():
            for item in items:
                entry = item['entry']
                time_str = item['time_str']
                
                # Получаем значение из кэша
                current_value = cell_values.get((row, col), "")
                
                # Заменяем @ на время в тексте
                if '@' in text:
                    text = html.unescape(text)
                    formatted_text = text.replace('@', time_str)
                else:
                    formatted_text = text
                
                # Проверяем возможность записи
                if current_value and str(current_value).strip():
                    if color_name == "голубой":
                        new_text = f"{current_value}, {formatted_text}"
                        entry["status"] = "success"
                        entry["message"] = "Текст дополнен"
                    else:
                        entry["status"] = "skip"
                        entry["message"] = "Ячейка занята (не голубой)"
                        report_data.append(entry)
                        continue
                else:
                    new_text = formatted_text
                    entry["status"] = "success"
                    entry["message"] = "Текст записан"
                
                # Формируем запрос на обновление
                requests.append({
                    'updateCells': {
                        'range': {
                            'sheetId': sheet.id,
                            'startRowIndex': row - 1,
                            'endRowIndex': row,
                            'startColumnIndex': col - 1,
                            'endColumnIndex': col
                        },
                        'rows': [{
                            'values': [{
                                'userEnteredValue': {'stringValue': new_text},
                                'userEnteredFormat': {'backgroundColor': color}
                            }]
                        }],
                        'fields': 'userEnteredValue,userEnteredFormat.backgroundColor'
                    }
                })
                report_data.append(entry)
        
        # Отправляем запросы с задержкой
        if requests:
            for i in range(0, len(requests), 10):  # Разбиваем на пакеты по 10
                batch = requests[i:i+10]
                sheet.spreadsheet.batch_update({'requests': batch})
                await asyncio.sleep(1)  # Задержка 1 сек между пакетами
            
        # Формируем отчет
        success_messages = []
        skip_messages = []
        error_messages = []
        
        for entry in report_data:
            channel_name = entry['channel']
            time_str = entry['time']
            
            # Экранируем специальные символы
            channel_name_escaped = html.escape(channel_name)
            time_str_escaped = html.escape(time_str)
            
            channel_link = CHANNELS_DICT.get(channel_name)
            
            if channel_link:
                channel_info = f"<a href='{channel_link}'>{channel_name_escaped}</a> ({time_str_escaped})"
            else:
                channel_info = f"{channel_name_escaped} ({time_str_escaped})"
                
            if entry["status"] == "success":
                success_messages.append(f"{channel_info}: {entry['message']}")
            elif entry["status"] == "skip":
                skip_messages.append(f"{channel_info}: {entry['message']}")
            elif entry["status"] == "error":
                error_messages.append(f"{channel_info}: {entry['message']}")
        

        report = ""
        if success_messages:
            report += "✅ Успешно:\n" + "\n".join(success_messages) + "\n\n"
        if skip_messages:
            report += "⏩ Пропущено:\n" + "\n".join(skip_messages) + "\n\n"
        if error_messages:
            report += "❌ Ошибки:\n" + "\n".join(error_messages) + "\n\n"
            
        return report.strip()
            
    except Exception as e:
        logger.error(f"Ошибка при обновлении таблицы: {e}")
        raise


# В sheets.py

# Обновим функцию cancel_table_cells
async def cancel_table_cells(client, target_date, day, channels_data):
    try:
        sheet_name = get_sheet_name(target_date)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = get_or_create_sheet(spreadsheet, sheet_name)
        
        # Для сбора запросов
        requests = []
        report_data = []
        
        # ЗЕЛЕНЫЙ ЦВЕТ ДЛЯ ОТМЕНЫ
        green_color = {"red": 0, "green": 1, "blue": 0}
        
        for data in channels_data:
            channel_name = data['channel']
            time_str = data['time']
            entry = {
                "channel": channel_name,
                "time": time_str,
                "status": None,
                "message": ""
            }
            
            try:
                channel_idx = CHANNELS.index(channel_name)
            except ValueError:
                entry["status"] = "error"
                entry["message"] = f"Канал '{channel_name}' не найден"
                report_data.append(entry)
                continue
            
            # Определяем положение таблицы
            tables_per_row = TABLE_CONFIG['tables_per_row']
            row_idx = channel_idx // tables_per_row
            col_idx = channel_idx % tables_per_row
            
            table_config = TABLE_CONFIG
            start_row = 2 + row_idx * (table_config['table_height'] + table_config['v_spacing'])
            start_col = 1 + col_idx * (table_config['table_width'] + table_config['h_spacing'])
            
            # Определяем строку дня
            row = start_row + day
            
            # Определяем смену по времени
            def get_shift(time_str):
                try:
                    hours = int(time_str.split(':')[0])
                    if 6 <= hours < 12: return 'morning'
                    elif 12 <= hours < 15: return 'afternoon'
                    elif 15 <= hours < 18: return 'day'
                    else: return 'evening'
                except: return 'evening'
            
            shift = get_shift(time_str)
            shift_columns = {
                'morning': 2, 'afternoon': 3, 'day': 4, 'evening': 5
            }
            col = start_col + shift_columns.get(shift, 5)
            
            # Добавляем запрос на очистку ячейки И ЗЕЛЕНЫЙ ЦВЕТ
            requests.append({
                'updateCells': {
                    'range': {
                        'sheetId': sheet.id,
                        'startRowIndex': row-1,
                        'endRowIndex': row,
                        'startColumnIndex': col-1,
                        'endColumnIndex': col
                    },
                    'rows': [{
                        'values': [{
                            'userEnteredValue': {'stringValue': ''},   # пустая строка
                            'userEnteredFormat': {
                                'backgroundColor': green_color  # ЗЕЛЕНЫЙ ЦВЕТ
                            }
                        }]
                    }],
                    'fields': 'userEnteredValue,userEnteredFormat.backgroundColor'
                }
            })
            
            entry["status"] = "success"
            entry["message"] = "Ячейка отменена (зеленая)"
            report_data.append(entry)
        
        # Отправляем запросы
        if requests:
            for i in range(0, len(requests), 10):  # Разбиваем на пакеты по 10
                batch = requests[i:i+10]
                sheet.spreadsheet.batch_update({'requests': batch})
                await asyncio.sleep(0.5)  # Короткая задержка
        
        # Формируем отчет
        success_messages = []
        error_messages = []
        
        for entry in report_data:
            channel_name = entry['channel']
            time_str = entry['time']
            
            # Экранируем специальные символы
            channel_name_escaped = html.escape(channel_name)
            time_str_escaped = html.escape(time_str)
            
            channel_link = CHANNELS_DICT.get(channel_name)
            
            if channel_link:
                channel_info = f"<a href='{channel_link}'>{channel_name_escaped}</a> ({time_str_escaped})"
            else:
                channel_info = f"{channel_name_escaped} ({time_str_escaped})"
                
            if entry["status"] == "success":
                success_messages.append(f"{channel_info}: {entry['message']}")
            elif entry["status"] == "error":
                error_messages.append(f"{channel_info}: {entry['message']}")
                
        report = ""
        if success_messages:
            report += "✅ Успешно:\n" + "\n".join(success_messages) + "\n\n"
        if error_messages:
            report += "❌ Ошибки:\n" + "\n".join(error_messages) + "\n\n"
            
        return report.strip()
            
    except Exception as e:
        logger.error(f"Ошибка при отмене записи: {e}")
        raise