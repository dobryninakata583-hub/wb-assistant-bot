#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Telegram-бот с настройкой отслеживаемых товаров и стратегий
"""

import os
import sys
import time
import requests
import threading
import schedule
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(__file__))

from config import Config, STRATEGIES
from wb_analyzer_fast import FastWBAnalyzer

load_dotenv()

# ============================================
# НАСТРОЙКИ ПЕРИОДОВ АНАЛИЗА
# ============================================

ANALYSIS_DAYS = {
    'status': int(os.getenv('ANALYSIS_DAYS_SHORT', '7')),      # утренняя сводка
    'analyze': int(os.getenv('ANALYSIS_DAYS_SHORT', '7')),     # полный анализ
    'product': int(os.getenv('ANALYSIS_DAYS_DETAIL', '14')),   # детальный анализ товара
    'trend': int(os.getenv('ANALYSIS_DAYS_TREND', '30'))       # анализ трендов
}

class ConfigurableBot:
    """Telegram-бот с поддержкой настраиваемых стратегий"""
    
    def __init__(self):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.allowed_users = [int(id.strip()) for id in os.getenv('ALLOWED_USER_IDS', '').split(',') if id.strip()]
        
        if not self.token:
            raise ValueError("❌ TELEGRAM_BOT_TOKEN не найден в .env")
        
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.last_update_id = 0
        
        # Инициализируем компоненты
        self.config = Config()
        self.analyzer = FastWBAnalyzer()
        
        # Состояния пользователей для диалогов
        self.user_states = {}
    
    # ============================================
    # БАЗОВЫЕ МЕТОДЫ РАБОТЫ С TELEGRAM
    # ============================================
    
    def send_message(self, chat_id: int, text: str, parse_mode: str = None) -> bool:
        """Отправляет сообщение в Telegram"""
        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        
        for attempt in range(3):
            try:
                response = requests.post(url, json=data, timeout=10)
                if response.status_code == 200:
                    return True
                else:
                    print(f"Ошибка отправки (попытка {attempt + 1}): {response.status_code}")
            except Exception as e:
                print(f"Ошибка отправки (попытка {attempt + 1}): {e}")
            time.sleep(2)
        return False
    
    def send_with_keyboard(self, chat_id: int, text: str, buttons: list, parse_mode: str = None) -> bool:
        """Отправляет сообщение с клавиатурой"""
        url = f"{self.base_url}/sendMessage"
        keyboard = {
            "keyboard": buttons,
            "resize_keyboard": True,
            "one_time_keyboard": True
        }
        data = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": keyboard
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Ошибка отправки клавиатуры: {e}")
            return False
    
    def get_updates(self) -> list:
        """Получает новые обновления от Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {
            "offset": self.last_update_id + 1,
            "timeout": 10
        }
        
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok") and data.get("result"):
                        return data["result"]
                    return []
                else:
                    print(f"Ошибка получения обновлений (попытка {attempt + 1}): {response.status_code}")
            except Exception as e:
                print(f"Ошибка получения обновлений (попытка {attempt + 1}): {e}")
            time.sleep(2)
        return []
    
    def check_auth(self, user_id: int) -> bool:
        """Проверяет, авторизован ли пользователь"""
        return user_id in self.allowed_users
    
    # ============================================
    # ПОКАЗ СПИСКОВ СТРАТЕГИЙ
    # ============================================
    
    def show_primary_strategies(self, chat_id: int, article: str):
        """Показывает список основных стратегий для выбора"""
        message = f"🎯 *Выберите ОСНОВНУЮ стратегию для товара `{article}`*\n\n"
        message += "Это главная цель работы с товаром. Дополнительную стратегию можно будет добавить позже.\n\n"
        
        buttons = []
        for key, strategy in STRATEGIES.items():
            message += f"{key}. {strategy['name']}\n   _{strategy['description']}_\n\n"
            buttons.append([key])
        
        self.send_with_keyboard(chat_id, message, buttons, parse_mode='Markdown')
    
    def show_secondary_strategies(self, chat_id: int, article: str, primary: str):
        """Показывает список разрешенных дополнительных стратегий"""
        allowed_names = self.config.get_allowed_secondary(primary)
        
        if not allowed_names:
            self.send_message(chat_id, 
                            f"ℹ️ Для стратегии {primary} нет доступных дополнительных стратегий.\n"
                            f"Настройка завершена.")
            return
        
        message = f"✨ *Выберите ДОПОЛНИТЕЛЬНУЮ стратегию для товара `{article}`*\n"
        message += f"(основная: {primary})\n\n"
        message += "Дополнительная стратегия поможет усилить эффект от основной. Можно пропустить этот шаг.\n\n"
        
        buttons = []
        for key, strategy in STRATEGIES.items():
            if strategy['name'] in allowed_names:
                message += f"{key}. {strategy['name']}\n   _{strategy['description']}_\n\n"
                buttons.append([key])
        
        message += "\n0. ➡️ Пропустить (только основная)"
        buttons.append(['0'])
        
        self.send_with_keyboard(chat_id, message, buttons, parse_mode='Markdown')
    
    # ============================================
    # ОБРАБОТКА ДИАЛОГОВ
    # ============================================
    
    def handle_state(self, user_id: int, chat_id: int, text: str):
        """Обрабатывает состояние диалога пользователя"""
        state = self.user_states.get(user_id)
        if not state:
            return
        
        action = state.get('action')
        
        # ===== ДОБАВЛЕНИЕ ТОВАРА =====
        if action == 'add_product':
            step = state.get('step')
            
            if step == 'waiting_article':
                article = text.strip()
                
                all_articles = self.analyzer.get_all_articles()
                
                if article not in all_articles:
                    self.send_message(chat_id, 
                                    f"❌ Артикул `{article}` не найден в таблице!\n\n"
                                    f"Проверьте правильность артикула или загрузите данные в таблицу.",
                                    parse_mode='Markdown')
                    del self.user_states[user_id]
                    return
                
                if self.config.add_product(article):
                    self.send_message(chat_id, f"✅ Товар `{article}` добавлен в отслеживание!", parse_mode='Markdown')
                    
                    self.user_states[user_id] = {
                        'action': 'add_product',
                        'step': 'waiting_primary_strategy',
                        'article': article
                    }
                    
                    self.show_primary_strategies(chat_id, article)
                    
                else:
                    self.send_message(chat_id, f"⚠️ Товар `{article}` уже отслеживается", parse_mode='Markdown')
                    del self.user_states[user_id]
            
            elif step == 'waiting_primary_strategy':
                article = state.get('article')
                
                if text in STRATEGIES:
                    primary = STRATEGIES[text]['name']
                    
                    self.config.set_strategy(article, primary, None)
                    
                    self.user_states[user_id] = {
                        'action': 'add_product',
                        'step': 'waiting_secondary_strategy',
                        'article': article,
                        'primary': primary
                    }
                    
                    self.show_secondary_strategies(chat_id, article, primary)
                    
                else:
                    self.send_message(chat_id, "❌ Пожалуйста, выберите стратегию из списка")
            
            elif step == 'waiting_secondary_strategy':
                article = state.get('article')
                primary = state.get('primary')
                
                if text == '0':
                    self.config.set_strategy(article, primary, None)
                    self.send_message(chat_id, 
                                    f"✅ Настройки сохранены!\n\n"
                                    f"Товар `{article}`\n"
                                    f"🎯 Основная: {primary}", 
                                    parse_mode='Markdown')
                    del self.user_states[user_id]
                    
                elif text in STRATEGIES:
                    secondary = STRATEGIES[text]['name']
                    allowed = self.config.get_allowed_secondary(primary)
                    
                    if secondary in allowed:
                        self.config.set_strategy(article, primary, secondary)
                        self.send_message(chat_id, 
                                        f"✅ Настройки сохранены!\n\n"
                                        f"Товар `{article}`\n"
                                        f"🎯 Основная: {primary}\n"
                                        f"✨ Дополнительная: {secondary}", 
                                        parse_mode='Markdown')
                        del self.user_states[user_id]
                    else:
                        self.send_message(chat_id, 
                                        f"❌ Эта комбинация недоступна!\n\n"
                                        f"Для стратегии {primary} нельзя добавить {secondary}.\n"
                                        f"Выберите другую дополнительную стратегию или 0 для пропуска.")
                else:
                    self.send_message(chat_id, "❌ Пожалуйста, выберите стратегию из списка или 0 для пропуска")
        
        # ===== УДАЛЕНИЕ ТОВАРА =====
        elif action == 'remove_product':
            step = state.get('step')
            if step == 'waiting_article':
                article = text.strip()
                if self.config.remove_product(article):
                    self.send_message(chat_id, f"🗑️ Товар `{article}` удален из отслеживания", parse_mode='Markdown')
                else:
                    self.send_message(chat_id, f"❌ Товар `{article}` не найден в списке", parse_mode='Markdown')
                del self.user_states[user_id]
        
        # ===== РЕДАКТИРОВАНИЕ СТРАТЕГИИ =====
        elif action == 'edit_strategy':
            step = state.get('step')
            if step == 'waiting_primary':
                article = state.get('article')
                if text in STRATEGIES:
                    primary = STRATEGIES[text]['name']
                    self.config.update_strategy(article, primary=primary, secondary=None)
                    self.send_message(chat_id, 
                                    f"✅ Стратегия обновлена!\n\n"
                                    f"Товар `{article}`\n"
                                    f"🎯 Новая основная: {primary}", 
                                    parse_mode='Markdown')
                    self.user_states[user_id] = {
                        'action': 'edit_strategy',
                        'step': 'waiting_secondary',
                        'article': article,
                        'primary': primary
                    }
                    self.show_secondary_strategies(chat_id, article, primary)
                else:
                    self.send_message(chat_id, "❌ Пожалуйста, выберите стратегию из списка")
            
            elif step == 'waiting_secondary':
                article = state.get('article')
                primary = state.get('primary')
                
                if text == '0':
                    self.config.update_strategy(article, secondary=None)
                    self.send_message(chat_id, "✅ Дополнительная стратегия не выбрана")
                    del self.user_states[user_id]
                elif text in STRATEGIES:
                    secondary = STRATEGIES[text]['name']
                    allowed = self.config.get_allowed_secondary(primary)
                    if secondary in allowed:
                        self.config.update_strategy(article, secondary=secondary)
                        self.send_message(chat_id, f"✅ Дополнительная стратегия: {secondary}")
                        del self.user_states[user_id]
                    else:
                        self.send_message(chat_id, 
                                        f"❌ Комбинация {primary} + {secondary} недоступна!\n"
                                        f"Выберите другую или 0 для пропуска")
                else:
                    self.send_message(chat_id, "❌ Выберите стратегию из списка или 0 для пропуска")
    
    # ============================================
    # ОБРАБОТКА КОМАНД
    # ============================================
    
    def handle_command(self, message: dict):
        """Обрабатывает команду от пользователя"""
        chat_id = message['chat']['id']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        
        if not self.check_auth(user_id):
            self.send_message(chat_id, "⛔ У вас нет доступа к этому боту.")
            return
        
        if user_id in self.user_states:
            self.handle_state(user_id, chat_id, text)
            return
        
        if text == '/start':
            self.cmd_start(chat_id)
        elif text == '/help':
            self.cmd_help(chat_id)
        elif text == '/list':
            self.cmd_list(chat_id)
        elif text.startswith('/add '):
            article = text.replace('/add ', '').strip()
            self.cmd_add_direct(chat_id, user_id, article)
        elif text == '/add':
            self.cmd_add_prompt(chat_id, user_id)
        elif text.startswith('/remove '):
            article = text.replace('/remove ', '').strip()
            self.cmd_remove_direct(chat_id, article)
        elif text == '/remove':
            self.cmd_remove_prompt(chat_id, user_id)
        elif text.startswith('/edit '):
            article = text.replace('/edit ', '').strip()
            self.cmd_edit_direct(chat_id, user_id, article)
        elif text == '/edit':
            self.cmd_edit_prompt(chat_id, user_id)
        elif text == '/clear':
            self.cmd_clear(chat_id, user_id)
        elif text == '/analyze':
            self.cmd_analyze(chat_id)
        elif text == '/status':
            self.cmd_status(chat_id)
        elif text.startswith('/product '):
            article = text.replace('/product ', '').strip()
            self.cmd_product(chat_id, article)
        else:
            self.send_message(chat_id, "❌ Неизвестная команда. Введите /help")
    
    # ============================================
    # РЕАЛИЗАЦИЯ КОМАНД
    # ============================================
    
    def cmd_start(self, chat_id: int):
        """Обработка команды /start"""
        welcome = """
👋 *Wildberries Ассистент* (настраиваемая версия)

Я помогаю отслеживать ваши товары и даю рекомендации по стратегиям продвижения.

*Основные команды:*

📋 *Управление товарами:*
/add АРТИКУЛ - добавить товар
/list - список всех товаров
/edit АРТИКУЛ - изменить стратегию
/remove АРТИКУЛ - удалить товар
/clear - очистить весь список

📊 *Аналитика:*
/status - общий статус (утренняя сводка)
/analyze - полный анализ всех товаров
/product АРТИКУЛ - детальный анализ конкретного товара

ℹ️ /help - все команды
"""
        self.send_message(chat_id, welcome, parse_mode='Markdown')
    
    def cmd_help(self, chat_id: int):
        """Обработка команды /help"""
        help_text = f"""
📚 *ПОЛНЫЙ СПИСОК КОМАНД*

*Добавление товаров:*
/add 123456 - добавить товар с артикулом 123456
/add (без артикула) - интерактивный режим

*Просмотр:*
/list - список всех товаров со стратегиями

*Редактирование:*
/edit 123456 - изменить стратегию для товара
/edit - интерактивный выбор товара для редактирования

*Удаление:*
/remove 123456 - удалить конкретный товар
/remove - интерактивное удаление
/clear - удалить ВСЕ товары

*Анализ:*
/status - общий статус (за {ANALYSIS_DAYS['status']} дней, без сегодня)
/analyze - полный анализ (за {ANALYSIS_DAYS['analyze']} дней)
/product АРТИКУЛ - детальный анализ (за {ANALYSIS_DAYS['product']} дней)

*Другое:*
/start - приветствие
/help - эта справка
"""
        self.send_message(chat_id, help_text, parse_mode='Markdown')
    
    def cmd_list(self, chat_id: int):
        """Показывает список отслеживаемых товаров"""
        result = self.config.format_list()
        self.send_message(chat_id, result, parse_mode='Markdown')
    
    def cmd_add_direct(self, chat_id: int, user_id: int, article: str):
        """Прямое добавление товара по артикулу с проверкой существования"""
        all_articles = self.analyzer.get_all_articles()
        
        if article not in all_articles:
            self.send_message(chat_id, 
                            f"❌ Артикул `{article}` не найден в таблице!\n\n"
                            f"Проверьте правильность артикула или загрузите данные в таблицу.",
                            parse_mode='Markdown')
            return
        
        if self.config.add_product(article):
            self.send_message(chat_id, f"✅ Товар `{article}` добавлен!", parse_mode='Markdown')
            self.user_states[user_id] = {
                'action': 'add_product',
                'step': 'waiting_primary_strategy',
                'article': article
            }
            self.show_primary_strategies(chat_id, article)
        else:
            self.send_message(chat_id, f"⚠️ Товар `{article}` уже отслеживается", parse_mode='Markdown')
    
    def cmd_add_prompt(self, chat_id: int, user_id: int):
        """Интерактивное добавление товара"""
        self.user_states[user_id] = {
            'action': 'add_product',
            'step': 'waiting_article'
        }
        self.send_message(chat_id, "📝 Введите артикул товара для добавления:")
    
    def cmd_remove_direct(self, chat_id: int, article: str):
        """Прямое удаление товара по артикулу"""
        if self.config.remove_product(article):
            self.send_message(chat_id, f"🗑️ Товар `{article}` удален", parse_mode='Markdown')
        else:
            self.send_message(chat_id, f"❌ Товар `{article}` не найден", parse_mode='Markdown')
    
    def cmd_remove_prompt(self, chat_id: int, user_id: int):
        """Интерактивное удаление товара"""
        products = self.config.get_all_products()
        if not products:
            self.send_message(chat_id, "📋 Список отслеживаемых товаров пуст")
            return
        
        self.user_states[user_id] = {
            'action': 'remove_product',
            'step': 'waiting_article'
        }
        message = "🗑️ *Введите артикул для удаления:*\n\n"
        for p in products:
            message += f"• `{p}`\n"
        self.send_message(chat_id, message, parse_mode='Markdown')
    
    def cmd_edit_direct(self, chat_id: int, user_id: int, article: str):
        """Прямое редактирование стратегии товара"""
        products = self.config.get_all_products()
        if article not in products:
            self.send_message(chat_id, f"❌ Товар `{article}` не найден в списке", parse_mode='Markdown')
            return
        
        self.user_states[user_id] = {
            'action': 'edit_strategy',
            'step': 'waiting_primary',
            'article': article
        }
        current = self.config.get_strategy(article)
        primary = current.get('primary', 'не выбрана')
        secondary = current.get('secondary')
        
        msg = f"✏️ *Редактирование стратегии для товара `{article}`*\n\n"
        msg += f"Текущая основная: {primary}\n"
        if secondary:
            msg += f"Текущая дополнительная: {secondary}\n\n"
        else:
            msg += "Дополнительная: не выбрана\n\n"
        
        self.send_message(chat_id, msg, parse_mode='Markdown')
        self.show_primary_strategies(chat_id, article)
    
    def cmd_edit_prompt(self, chat_id: int, user_id: int):
        """Интерактивное редактирование"""
        products = self.config.get_all_products()
        if not products:
            self.send_message(chat_id, "📋 Список отслеживаемых товаров пуст")
            return
        
        message = "✏️ *Введите артикул для редактирования:*\n\n"
        for p in products:
            message += f"• `{p}`\n"
        self.send_message(chat_id, message, parse_mode='Markdown')
    
    def cmd_clear(self, chat_id: int, user_id: int):
        """Очистка всего списка"""
        self.user_states[user_id] = {
            'action': 'confirm_clear',
            'step': 'waiting_confirm'
        }
        self.send_message(chat_id, 
                         "⚠️ *Вы уверены?*\n\n"
                         "Это удалит ВСЕ товары из отслеживания.\n"
                         "Отправьте 'ДА' для подтверждения или 'НЕТ' для отмены.",
                         parse_mode='Markdown')
    
    def cmd_status(self, chat_id: int):
        """Краткий статус по всем товарам (утренняя сводка)"""
        days = ANALYSIS_DAYS['status']
        products = self.config.get_all_products()
        
        if not products:
            self.send_message(chat_id, "📋 Список отслеживаемых товаров пуст")
            return
        
        self.send_message(chat_id, f"📊 *Формирую утреннюю сводку за {days} дней (без сегодня)...*\nАнализирую {len(products)} товаров", parse_mode='Markdown')
        
        try:
            products_df = self.analyzer.get_products_data(days=days)
            ads_df = self.analyzer.get_ads_data(days=days)
            
            results = self.analyzer.analyze_selected_products(products_df, ads_df, products)
            
            if not results:
                self.send_message(chat_id, "❌ Нет данных по выбранным товарам")
                return
            
            critical = []
            warnings = []
            normal = []
            
            for r in results:
                if any('🔴' in p for p in r.get('problems', [])):
                    critical.append(r)
                elif r.get('problems'):
                    warnings.append(r)
                else:
                    normal.append(r)
            
            today = datetime.now().strftime('%d.%m.%Y')
            msg = f"📅 *Утренняя сводка на {today} (за {days} дней, без сегодня)*\n\n"
            
            msg += f"📊 *Всего отслеживается:* {len(products)} товаров\n"
            msg += f"📦 *Найдено данных:* {len(results)} товаров\n\n"
            
            if critical:
                msg += f"🔴 *КРИТИЧЕСКИЕ ПРОБЛЕМЫ ({len(critical)}):*\n"
                for r in critical[:5]:
                    strategy = r.get('strategy', 'Не выбрана')
                    msg += f"• `{r['ID']}` ({strategy})\n"
                    for prob in r['problems'][:2]:
                        msg += f"  {prob}\n"
                    msg += "\n"
            
            if warnings:
                msg += f"⚠️ *ТРЕБУЮТ ВНИМАНИЯ ({len(warnings)}):*\n"
                for r in warnings[:5]:
                    strategy = r.get('strategy', 'Не выбрана')
                    msg += f"• `{r['ID']}` ({strategy})\n"
                    for prob in r['problems'][:1]:
                        msg += f"  {prob}\n"
                if len(warnings) > 5:
                    msg += f"...и еще {len(warnings) - 5} товаров\n"
                msg += "\n"
            
            if normal:
                msg += f"✅ *В НОРМЕ:* {len(normal)} товаров\n"
                examples = [f"`{r['ID']}`" for r in normal[:3]]
                if examples:
                    msg += f"  Например: {', '.join(examples)}\n"
            
            msg += "\n📌 *Детальный анализ:*\n"
            msg += "/analyze - полный отчет по всем\n"
            msg += "/product АРТИКУЛ - анализ конкретного товара"
            
            self.send_message(chat_id, msg, parse_mode='Markdown')
            
            if critical:
                quick_msg = "⚡ *Быстрые действия:*\n"
                for r in critical[:3]:
                    quick_msg += f"• /product {r['ID']} - анализ проблемного товара\n"
                self.send_message(chat_id, quick_msg, parse_mode='Markdown')
            
        except Exception as e:
            self.send_message(chat_id, f"❌ Ошибка анализа: {e}")
    
    def cmd_analyze(self, chat_id: int):
        """Полный анализ всех товаров с рекомендациями"""
        days = ANALYSIS_DAYS['analyze']
        products = self.config.get_all_products()
        
        if not products:
            self.send_message(chat_id, "📋 Список отслеживаемых товаров пуст")
            return
        
        self.send_message(chat_id, f"🔍 Запускаю полный анализ {len(products)} товаров за {days} дней (без сегодня)...\nЭто займет 1-2 минуты", parse_mode='Markdown')
        
        try:
            products_df = self.analyzer.get_products_data(days=days)
            ads_df = self.analyzer.get_ads_data(days=days)
            
            results = self.analyzer.analyze_selected_products(products_df, ads_df, products)
            
            if not results:
                self.send_message(chat_id, "❌ Нет данных по выбранным товарам")
                return
            
            results = self.analyzer.add_recommendations_batch(results, detailed=False)
            
            for r in results:
                msg = f"📦 *Товар {r['ID']}*\n"
                msg += f"📅 Данные на: {r['last_date']}\n"
                
                if r.get('strategy'):
                    msg += f"🎯 Стратегия: {r['strategy']}"
                    if r.get('secondary_strategy'):
                        msg += f" + {r['secondary_strategy']}"
                    msg += "\n"
                
                msg += f"📦 Остаток: {r['stock']:.0f} шт\n"
                msg += f"📈 Продажи (ср. за {days} дней): {r['avg_sales']:.1f} шт/день\n"
                
                if r.get('sales_dynamics') and r['sales_dynamics'] != 0:
                    trend = "📈" if r['sales_dynamics'] > 0 else "📉"
                    msg += f"   Динамика: {trend} {r['sales_dynamics']:.1f}%\n"
                
                if r['spend'] > 0:
                    msg += f"📢 Реклама (за {days} дней): {r['spend']:.0f} руб, CTR: {r['ctr']:.1f}%\n"
                    if r['avg_cpc'] > 0:
                        msg += f"   Средний CPC: {r['avg_cpc']:.2f} руб\n"
                
                if r.get('problems'):
                    msg += "⚠️ *Проблемы:*\n"
                    for prob in r['problems']:
                        msg += f"  {prob}\n"
                
                if r.get('recommendation'):
                    msg += f"\n💡 *Рекомендация:*\n{r['recommendation']}\n"
                
                self.send_message(chat_id, msg, parse_mode='Markdown')
                time.sleep(1)
            
            self.send_message(chat_id, "✅ Анализ завершен!")
            
        except Exception as e:
            self.send_message(chat_id, f"❌ Ошибка анализа: {e}")
    
    def cmd_product(self, chat_id: int, article: str):
        """Детальный анализ конкретного товара с учетом его стратегий"""
        days = ANALYSIS_DAYS['product']
        products = self.config.get_all_products()
        
        if article not in products:
            self.send_message(chat_id, 
                            f"❌ Товар `{article}` не отслеживается.\n"
                            f"Добавьте его через /add {article}",
                            parse_mode='Markdown')
            return
        
        self.send_message(chat_id, f"🔍 Анализирую товар `{article}` за {days} дней (без сегодня)...", parse_mode='Markdown')
        
        try:
            products_df = self.analyzer.get_products_data(days=days)
            ads_df = self.analyzer.get_ads_data(days=days)
            
            results = self.analyzer.analyze_selected_products(products_df, ads_df, [article])
            
            if not results:
                self.send_message(chat_id, f"❌ Нет данных по товару `{article}`", parse_mode='Markdown')
                return
            
            product_data = results[0]
            strategy = self.config.get_strategy(article)
            primary = strategy.get('primary', 'Не выбрана')
            secondary = strategy.get('secondary')
            
            msg = f"📊 *ДЕТАЛЬНЫЙ АНАЛИЗ ТОВАРА (за {days} дней, без сегодня)*\n\n"
            msg += f"📦 *Артикул:* `{article}`\n"
            msg += f"📅 *Данные актуальны на:* {product_data['last_date']}\n"
            msg += f"🎯 *Стратегия:* {primary}\n"
            if secondary:
                msg += f"✨ *Дополнительно:* {secondary}\n"
            msg += "\n"
            
            msg += "📈 *Ключевые показатели:*\n"
            msg += f"• Остаток на складе (на вчера): {product_data['stock']:.0f} шт\n"
            msg += f"• Средние продажи (за {days} дней): {product_data['avg_sales']:.1f} шт/день\n"
            
            if product_data.get('sales_dynamics') and product_data['sales_dynamics'] != 0:
                trend = "📈" if product_data['sales_dynamics'] > 0 else "📉"
                msg += f"• Динамика продаж (день к дню): {trend} {product_data['sales_dynamics']:.1f}%\n"
            
            if product_data['avg_sales'] > 0:
                days_left = product_data['days_until_stockout']
                if days_left != float('inf'):
                    msg += f"• Прогноз иссякания: через {days_left:.0f} дней\n"
                else:
                    msg += f"• Прогноз иссякания: более 30 дней\n"
            else:
                msg += "• Прогноз иссякания: нет продаж\n"
            
            if product_data['spend'] > 0:
                msg += f"• Расход на рекламу (за {days} дней): {product_data['spend']:.0f} руб\n"
                msg += f"• CTR: {product_data['ctr']:.1f}%\n"
                if product_data['avg_cpc'] > 0:
                    msg += f"• Средний CPC: {product_data['avg_cpc']:.2f} руб\n"
                msg += f"• Показов: {product_data['impressions']}\n"
                msg += f"• Кликов: {product_data['clicks']}\n"
            
            if product_data.get('problems'):
                msg += "\n⚠️ *Выявленные проблемы:*\n"
                for prob in product_data['problems']:
                    msg += f"• {prob}\n"
            
            self.send_message(chat_id, msg, parse_mode='Markdown')
            
            self.send_message(chat_id, "💡 *Генерирую рекомендацию с учетом стратегий...*", parse_mode='Markdown')
            
            # Получаем развернутую рекомендацию от AI
            recommendation = self.analyzer.advisor.get_recommendation(product_data, detailed=True)
            final_msg = f"💡 *Рекомендация для товара `{article}`:*\n\n{recommendation}"
            self.send_message(chat_id, final_msg, parse_mode='Markdown')
            
        except Exception as e:
            self.send_message(chat_id, f"❌ Ошибка анализа: {e}")
    
    # ============================================
    # АВТОМАТИЧЕСКАЯ УТРЕННЯЯ СВОДКА
    # ============================================
    
    def send_morning_report(self):
        """Отправляет утреннюю сводку всем авторизованным пользователям"""
        days = ANALYSIS_DAYS['status']
        print(f"⏰ Отправка утренней сводки за {days} дней {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        
        products = self.config.get_all_products()
        
        if not products:
            return
        
        try:
            products_df = self.analyzer.get_products_data(days=days)
            ads_df = self.analyzer.get_ads_data(days=days)
            
            results = self.analyzer.analyze_selected_products(products_df, ads_df, products)
            
            if not results:
                return
            
            critical = [r for r in results if any('🔴' in p for p in r.get('problems', []))]
            warnings = [r for r in results if r.get('problems') and r not in critical]
            
            today = datetime.now().strftime('%d.%m.%Y')
            msg = f"📅 *Доброе утро! Ваша сводка на {today} (за {days} дней, без сегодня)*\n\n"
            
            msg += f"📊 *Всего товаров:* {len(products)}\n"
            msg += f"🔴 *Критических:* {len(critical)}\n"
            msg += f"⚠️ *Требуют внимания:* {len(warnings)}\n"
            msg += f"✅ *В норме:* {len(results) - len(critical) - len(warnings)}\n\n"
            
            if critical:
                msg += "🔴 *Проблемные товары:*\n"
                for r in critical[:5]:
                    msg += f"• `{r['ID']}`: {r['problems'][0]}\n"
            
            msg += "\n/status - полная сводка"
            msg += "\n/analyze - детальный анализ"
            
            for user_id in self.allowed_users:
                self.send_message(user_id, msg, parse_mode='Markdown')
                
        except Exception as e:
            print(f"❌ Ошибка отправки утренней сводки: {e}")
    
    # ============================================
    # ЗАПУСК БОТА
    # ============================================
    
    def run(self):
        """Запускает бота"""
        print("🚀 Запуск настроенного бота...")
        print(f"📋 Отслеживаемых товаров: {len(self.config.get_all_products())}")
        print(f"📊 Периоды анализа: статус={ANALYSIS_DAYS['status']}д, продукт={ANALYSIS_DAYS['product']}д")
        print("   (нажмите Ctrl+C для остановки)")
        
        def run_scheduler():
            schedule.every().day.at("09:00").do(self.send_morning_report)
            print("⏰ Планировщик утренних сводок запущен (каждый день в 9:00)")
            
            while True:
                schedule.run_pending()
                time.sleep(60)
        
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        
        while True:
            try:
                updates = self.get_updates()
                
                for update in updates:
                    self.last_update_id = update['update_id']
                    if 'message' in update:
                        self.handle_command(update['message'])
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                print("\n👋 Бот остановлен")
                break
            except Exception as e:
                print(f"❌ Неожиданная ошибка: {e}")
                time.sleep(5)


# ============================================
# ТОЧКА ВХОДА
# ============================================

if __name__ == "__main__":
    try:
        bot = ConfigurableBot()
        bot.run()
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()