#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Конфигурация отслеживаемых товаров и стратегий
"""

import json
import os
from typing import List, Dict, Optional

# ============================================
# СПИСОК ВСЕХ ДОСТУПНЫХ СТРАТЕГИЙ
# ============================================

STRATEGIES = {
    '1': {
        'id': '1',
        'name': '🚀 Вывод в топ',
        'description': 'Агрессивный рост, захват доли рынка (для сезонных и новых товаров)',
        'icon': '🚀'
    },
    '2': {
        'id': '2',
        'name': '📈 Поддержание продаж',
        'description': 'Стабильные продажи с контролем рентабельности (для всесезонных товаров)',
        'icon': '📈'
    },
    '3': {
        'id': '3',
        'name': '🏷️ Ликвидация остатков',
        'description': 'Быстрая распродажа залежавшегося товара, освобождение склада',
        'icon': '🏷️'
    },
    '4': {
        'id': '4',
        'name': '🏆 Удержание лидерства',
        'description': 'Защита позиций в топе, мониторинг конкурентов',
        'icon': '🏆'
    },
    '5': {
        'id': '5',
        'name': '🔄 Кросс-продажи',
        'description': 'Увеличение среднего чека за счет связанных товаров',
        'icon': '🔄'
    },
    '6': {
        'id': '6',
        'name': '⏰ Антикризисная',
        'description': 'Реагирование на форс-мажоры: резкие падения, проблемы с поставками',
        'icon': '⏰'
    },
    '7': {
        'id': '7',
        'name': '💎 Премиальная',
        'description': 'Высокая маржа, качество, работа с премиум-аудиторией',
        'icon': '💎'
    }
}

# ============================================
# ПРАВИЛА КОМБИНИРОВАНИЯ СТРАТЕГИЙ
# ============================================

# Для каждой основной стратегии указываем, какие дополнительные разрешены
STRATEGY_COMBINATIONS = {
    '🚀 Вывод в топ': {
        'allow': ['🔄 Кросс-продажи', '🏆 Удержание лидерства'],
        'reason': 'Вывод в топ требует агрессивных цен и больших остатков'
    },
    '📈 Поддержание продаж': {
        'allow': ['🔄 Кросс-продажи', '🏆 Удержание лидерства', '💎 Премиальная'],
        'reason': 'Поддержание — про стабильность, можно комбинировать с премиумом и кросс-продажами'
    },
    '🏷️ Ликвидация остатков': {
        'allow': ['🔄 Кросс-продажи', '⏰ Антикризисная'],
        'reason': 'Ликвидация — про освобождение склада любой ценой'
    },
    '🏆 Удержание лидерства': {
        'allow': ['🔄 Кросс-продажи', '📈 Поддержание продаж'],
        'reason': 'Удержание — защита позиций, можно комбинировать с поддержанием'
    },
    '🔄 Кросс-продажи': {
        'allow': ['🚀 Вывод в топ', '📈 Поддержание продаж', '🏷️ Ликвидация остатков', 
                  '🏆 Удержание лидерства', '💎 Премиальная', '⏰ Антикризисная'],
        'reason': 'Кросс-продажи универсальны и подходят к любым стратегиям'
    },
    '⏰ Антикризисная': {
        'allow': ['🏷️ Ликвидация остатков'],
        'reason': 'В кризисе нужно спасать, а не развивать'
    },
    '💎 Премиальная': {
        'allow': ['🔄 Кросс-продажи', '📈 Поддержание продаж'],
        'reason': 'Премиум не терпит демпинга и распродаж'
    }
}

# ============================================
# КЛАСС ДЛЯ РАБОТЫ С НАСТРОЙКАМИ
# ============================================

class Config:
    """Класс для работы с настройками отслеживаемых товаров"""
    
    def __init__(self, config_file: str = 'tracked_products.json'):
        """
        Инициализация конфига
        
        Args:
            config_file: путь к файлу с настройками
        """
        self.config_file = config_file
        self.data = self._load()
    
    def _load(self) -> Dict:
        """Загружает конфигурацию из файла"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # Если файл поврежден, создаем новый
                return {'products': [], 'strategies': {}}
        
        # Если файла нет, создаем пустую структуру
        return {'products': [], 'strategies': {}}
    
    def _save(self) -> None:
        """Сохраняет конфигурацию в файл"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"❌ Ошибка сохранения конфига: {e}")
    
    # ===== УПРАВЛЕНИЕ СПИСКОМ ТОВАРОВ =====
    
    def get_all_products(self) -> List[str]:
        """Возвращает список всех отслеживаемых товаров"""
        return self.data.get('products', [])
    
    def add_product(self, article: str) -> bool:
        """
        Добавляет товар в отслеживание
        
        Returns:
            True если товар добавлен, False если уже был
        """
        if article not in self.data['products']:
            self.data['products'].append(article)
            self._save()
            return True
        return False
    
    def remove_product(self, article: str) -> bool:
        """
        Удаляет товар из отслеживания
        
        Returns:
            True если товар удален, False если не найден
        """
        if article in self.data['products']:
            self.data['products'].remove(article)
            # Удаляем стратегии для этого товара
            if article in self.data.get('strategies', {}):
                del self.data['strategies'][article]
            self._save()
            return True
        return False
    
    def clear_all(self) -> None:
        """Удаляет все товары из отслеживания"""
        self.data['products'] = []
        self.data['strategies'] = {}
        self._save()
    
    # ===== УПРАВЛЕНИЕ СТРАТЕГИЯМИ =====
    
    def set_strategy(self, article: str, primary: str, secondary: Optional[str] = None) -> None:
        """
        Устанавливает стратегию для товара
        
        Args:
            article: артикул товара
            primary: основная стратегия (название)
            secondary: дополнительная стратегия (название) или None
        """
        if 'strategies' not in self.data:
            self.data['strategies'] = {}
        
        self.data['strategies'][article] = {
            'primary': primary,
            'secondary': secondary
        }
        self._save()
    
    def get_strategy(self, article: str) -> Dict:
        """
        Возвращает стратегию для товара
        
        Returns:
            словарь с ключами 'primary' и 'secondary'
        """
        return self.data.get('strategies', {}).get(article, {
            'primary': None,
            'secondary': None
        })
    
    def update_strategy(self, article: str, **kwargs) -> bool:
        """
        Обновляет стратегию товара
        
        Args:
            article: артикул
            **kwargs: поля для обновления ('primary', 'secondary')
        
        Returns:
            True если обновлено, False если товар не найден
        """
        if article not in self.data['products']:
            return False
        
        if article not in self.data.get('strategies', {}):
            self.data['strategies'][article] = {}
        
        for key, value in kwargs.items():
            if value is not None:
                self.data['strategies'][article][key] = value
        
        self._save()
        return True
    
    # ===== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =====
    
    def format_list(self) -> str:
        """Форматирует список товаров для вывода в Telegram"""
        products = self.get_all_products()
        
        if not products:
            return "📋 *Список отслеживаемых товаров*\n\n_Список пуст. Добавьте товары через /add_"
        
        result = "📋 *ОТСЛЕЖИВАЕМЫЕ ТОВАРЫ*\n\n"
        
        for i, article in enumerate(products, 1):
            strategy = self.get_strategy(article)
            primary = strategy.get('primary')
            secondary = strategy.get('secondary')
            
            result += f"{i}. `{article}` — "
            
            if primary:
                # Ищем иконку по названию стратегии
                icon = next((s['icon'] for s in STRATEGIES.values() if s['name'] == primary), '📌')
                result += f"{icon} *{primary}*"
                
                if secondary:
                    sec_icon = next((s['icon'] for s in STRATEGIES.values() if s['name'] == secondary), '✨')
                    result += f" + {sec_icon} {secondary}"
            else:
                result += "⚪ *Стратегия не выбрана*"
            
            result += "\n"
        
        result += f"\nВсего: {len(products)} товаров"
        result += "\n\n/edit - изменить стратегию"
        result += "\n/remove - удалить товар"
        
        return result
    
    def get_allowed_secondary(self, primary: str) -> List[str]:
        """
        Возвращает список разрешенных дополнительных стратегий для данной основной
        
        Args:
            primary: название основной стратегии
        
        Returns:
            список названий разрешенных дополнительных стратегий
        """
        if primary in STRATEGY_COMBINATIONS:
            return STRATEGY_COMBINATIONS[primary]['allow']
        return []


# ============================================
# ТЕСТИРОВАНИЕ
# ============================================

if __name__ == "__main__":
    print("🔧 Тестирование конфига...")
    cfg = Config("test_config.json")
    
    # Добавляем тестовые товары
    cfg.add_product("123456")
    cfg.set_strategy("123456", "🚀 Вывод в топ", "🔄 Кросс-продажи")
    
    cfg.add_product("789012")
    cfg.set_strategy("789012", "📈 Поддержание продаж", None)
    
    # Выводим список
    print(cfg.format_list())
    
    # Проверяем разрешенные комбинации
    print("\nРазрешенные для '🚀 Вывод в топ':", 
          cfg.get_allowed_secondary("🚀 Вывод в топ"))
    
    # Очищаем
    cfg.clear_all()
    print("\n✅ Тест завершен")