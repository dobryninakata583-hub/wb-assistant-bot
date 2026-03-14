#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Быстрый анализатор данных Wildberries с поддержкой параллельных запросов
"""

import os
import re
import time
import pandas as pd
import requests
import gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import Config

load_dotenv()

# ============================================
# AI-СОВЕТЧИК
# ============================================

class FastDeepSeekAdvisor:
    """Быстрый класс для получения рекомендаций от DeepSeek"""
    
    def __init__(self):
        self.api_url = os.getenv('DEEPSEEK_API_URL', 'http://localhost:11434/api/generate')
        self.model = os.getenv('DEEPSEEK_MODEL', 'deepseek-r1:1.5b')
        
    def get_recommendation(self, product_data: dict, detailed: bool = False) -> str:
        """
        Получает рекомендацию от DeepSeek
        
        Args:
            product_data: словарь с данными о товаре
            detailed: если True, дает развернутую рекомендацию (3-4 предложения)
        
        Returns:
            строка с рекомендацией
        """
        problems_text = product_data['problems'][0] if product_data.get('problems') else 'нет проблем'
        
        strategy_text = ""
        if product_data.get('strategy'):
            strategy_text = f"Основная стратегия: {product_data['strategy']}. "
        if product_data.get('secondary_strategy'):
            strategy_text += f"Дополнительно: {product_data['secondary_strategy']}. "
        
        if detailed:
            prompt = f"""{strategy_text}
Товар {product_data['ID']}: 
- Остаток (на вчера): {product_data['stock']:.0f} шт
- Средние продажи (за 7 дней): {product_data['avg_sales']:.1f} шт/день
- Прогноз иссякания: {product_data['days_until_stockout']:.0f} дней
- CTR (за 7 дней): {product_data['ctr']:.1f}%
- Расход на рекламу (за 7 дней): {product_data['spend']:.0f} руб
- Динамика продаж: {product_data.get('sales_dynamics', 0):.1f}%

Проблема: {problems_text}

Дай развернутую рекомендацию (3-4 предложения) с учетом выбранных стратегий. 
Объясни, что конкретно нужно сделать для достижения цели."""
        else:
            prompt = f"""{strategy_text}
Товар {product_data['ID']}: 
- Остаток (на вчера): {product_data['stock']:.0f} шт
- Продажи (средние за 7 дней): {product_data['avg_sales']:.1f} шт/день
- Проблема: {problems_text}

Дай ОДНУ короткую, конкретную рекомендацию (1-2 предложения), что делать продавцу."""
        
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "max_tokens": 300 if detailed else 150
                }
            }
            
            response = requests.post(self.api_url, json=payload, timeout=45 if detailed else 30)
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
            return "⚠️ Рекомендация временно недоступна"
                
        except Exception as e:
            print(f"   ❌ Ошибка AI: {e}")
            return "⚠️ Рекомендация временно недоступна"


# ============================================
# АНАЛИЗАТОР ДАННЫХ
# ============================================

class FastWBAnalyzer:
    """Быстрый анализатор данных Wildberries"""
    
    def __init__(self):
        """Подключаемся к Google-таблице"""
        credentials_file = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
        sheet_id = os.getenv('GOOGLE_SHEET_ID')
        
        if not credentials_file or not sheet_id:
            raise ValueError("❌ Не указаны GOOGLE_SHEETS_CREDENTIALS или GOOGLE_SHEET_ID в .env")
        
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
            client = gspread.authorize(credentials)
            self.sheet = client.open_by_key(sheet_id)
            print(f"✅ Подключено к таблице: {self.sheet.title}")
        except Exception as e:
            print(f"❌ Ошибка подключения к Google Sheets: {e}")
            raise
        
        self.advisor = FastDeepSeekAdvisor()
        self.config = Config()
    
    def get_all_articles(self) -> list:
        """Получает список всех уникальных артикулов из таблицы"""
        try:
            ws = self.sheet.worksheet("Данные по товарам (выгрузка)")
            data = ws.get_all_values()
            
            if len(data) < 2:
                return []
            
            headers = data[0]
            if 'ID' not in headers:
                return []
            
            id_col_idx = headers.index('ID')
            
            articles = set()
            for row in data[1:]:
                if len(row) > id_col_idx and row[id_col_idx]:
                    articles.add(row[id_col_idx].strip())
            
            return sorted(list(articles))
            
        except Exception as e:
            print(f"Ошибка получения списка артикулов: {e}")
            return []
    
    def clean_number(self, value) -> float:
        """Очищает число от лишних символов (пробелы, запятые, символы валют)"""
        if pd.isna(value) or value == '' or value is None:
            return 0.0
        
        value_str = str(value)
        # Убираем пробелы и неразрывные пробелы
        value_str = re.sub(r'\s+', '', value_str)
        value_str = value_str.replace('\xa0', '')
        value_str = value_str.replace(',', '.')
        
        # Извлекаем число (включая отрицательные и с десятичной точкой)
        match = re.search(r'-?\d+\.?\d*', value_str)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
        return 0.0
    
    def get_products_data(self, days: int = 7) -> pd.DataFrame:
        """
        Загружает данные по товарам за указанный период (без сегодняшнего дня)
        
        Args:
            days: количество дней для анализа (без учета сегодня)
        
        Returns:
            DataFrame с данными
        """
        print(f"📥 Загружаем данные по товарам за последние {days} дней (без сегодня)...")
        
        try:
            ws = self.sheet.worksheet("Данные по товарам (выгрузка)")
            data = ws.get_all_values()
            
            if len(data) < 2:
                print("   ⚠️ Нет данных")
                return pd.DataFrame()
            
            headers = data[0]
            rows = data[1:]
            
            df = pd.DataFrame(rows, columns=headers)
            
            if 'дата' in df.columns:
                df['дата'] = pd.to_datetime(df['дата'], format='%d.%m.%Y', errors='coerce')
                df = df.dropna(subset=['дата'])
            
            if not df.empty:
                # Последняя доступная дата в данных
                last_date = df['дата'].max()
                today = datetime.now().date()
                
                print(f"   Последняя дата в данных: {last_date.date()}")
                print(f"   Сегодня: {today}")
                
                # Если последняя дата - сегодня, исключаем её
                if last_date.date() == today:
                    print(f"   ⚠️ Исключаем сегодняшние данные (могут быть неполными)")
                    df_filtered = df[df['дата'] < pd.Timestamp(today)]
                    last_date = df_filtered['дата'].max() if not df_filtered.empty else None
                else:
                    df_filtered = df
                
                if df_filtered.empty:
                    print("   ⚠️ Нет данных за предыдущие дни")
                    return pd.DataFrame()
                
                # Берем данные за последние N дней (без сегодня)
                start_date = last_date - timedelta(days=days)
                df_filtered = df_filtered[df_filtered['дата'] >= start_date]
                
                print(f"   Период: с {start_date.date()} по {last_date.date()}")
                print(f"   Записей: {len(df_filtered)}")
                return df_filtered
            
            return df
            
        except Exception as e:
            print(f"   ❌ Ошибка загрузки товаров: {e}")
            return pd.DataFrame()
    
    def get_ads_data(self, days: int = 7) -> pd.DataFrame:
        """
        Загружает данные по рекламе за указанный период (без сегодняшнего дня)
        
        Args:
            days: количество дней для анализа (без учета сегодня)
        
        Returns:
            DataFrame с данными
        """
        print(f"📥 Загружаем данные по рекламе за последние {days} дней (без сегодня)...")
        
        try:
            ws = self.sheet.worksheet("Данные реклама (выгрузка)")
            data = ws.get_all_values()
            
            if len(data) < 2:
                print("   ⚠️ Нет данных по рекламе")
                return pd.DataFrame()
            
            headers = data[0]
            rows = data[1:]
            
            df = pd.DataFrame(rows, columns=headers)
            
            if 'Дата' in df.columns:
                df['Дата'] = pd.to_datetime(df['Дата'], format='%Y-%m-%d', errors='coerce')
                df = df.dropna(subset=['Дата'])
            
            if not df.empty:
                last_date = df['Дата'].max()
                today = datetime.now().date()
                
                print(f"   Последняя дата в данных: {last_date.date()}")
                print(f"   Сегодня: {today}")
                
                # Если последняя дата - сегодня, исключаем её
                if last_date.date() == today:
                    print(f"   ⚠️ Исключаем сегодняшние данные")
                    df_filtered = df[df['Дата'] < pd.Timestamp(today)]
                    last_date = df_filtered['Дата'].max() if not df_filtered.empty else None
                else:
                    df_filtered = df
                
                if df_filtered.empty:
                    return pd.DataFrame()
                
                start_date = last_date - timedelta(days=days)
                df_filtered = df_filtered[df_filtered['Дата'] >= start_date]
                
                print(f"   Период: с {start_date.date()} по {last_date.date()}")
                print(f"   Записей: {len(df_filtered)}")
                return df_filtered
            
            return df
            
        except Exception as e:
            print(f"   ⚠️ Нет данных по рекламе: {e}")
            return pd.DataFrame()
    
    def process_one_product(self, args) -> dict:
        """
        Обрабатывает один товар (для параллельного выполнения)
        
        Args:
            args: кортеж (product_id, product_data, ads_df)
        
        Returns:
            словарь с данными товара или None
        """
        product_id, product_data, ads_df = args
        
        try:
            # Сортируем по дате и берем самую последнюю запись (вчерашнюю)
            product_data = product_data.sort_values('дата', ascending=False)
            
            if len(product_data) == 0:
                return None
                
            latest = product_data.iloc[0]  # Вчерашний день
            previous = product_data.iloc[1] if len(product_data) > 1 else None
            
            # Продажи за весь период (средние)
            sales_values = []
            for val in product_data['продажи']:
                cleaned = self.clean_number(val)
                sales_values.append(cleaned)
            avg_sales = sum(sales_values) / len(sales_values) if sales_values else 0.0
            
            # Остаток за ВЧЕРАШНИЙ день
            stock = self.clean_number(latest['остаток'])
            
            # Динамика продаж (сравнение вчера с позавчера)
            sales_dynamics = 0
            if previous is not None:
                prev_sales = self.clean_number(previous['продажи'])
                current_sales = self.clean_number(latest['продажи'])
                if prev_sales > 0:
                    sales_dynamics = ((current_sales - prev_sales) / prev_sales) * 100
            
            # Реклама для этого товара
            if not ads_df.empty and 'Артикул' in ads_df.columns:
                product_ads = ads_df[ads_df['Артикул'] == product_id]
            else:
                product_ads = pd.DataFrame()
            
            total_spend = 0.0
            total_impressions = 0
            total_clicks = 0
            ctr = 0.0
            avg_cpc = 0.0
            
            if len(product_ads) > 0:
                spend_values = []
                for val in product_ads['Бюджет']:
                    spend_values.append(self.clean_number(val))
                total_spend = sum(spend_values) if spend_values else 0.0
                
                impressions_values = []
                for val in product_ads['Просмотры']:
                    val_str = str(val).replace('\xa0', ' ').replace(' ', '')
                    impressions_values.append(self.clean_number(val_str))
                total_impressions = int(sum(impressions_values)) if impressions_values else 0
                
                clicks_values = []
                for val in product_ads['Клики']:
                    clicks_values.append(self.clean_number(val))
                total_clicks = int(sum(clicks_values)) if clicks_values else 0
                
                if total_impressions > 0:
                    ctr = (total_clicks / total_impressions) * 100
                if total_clicks > 0:
                    avg_cpc = total_spend / total_clicks
            
            # Прогноз иссякания на основе средних продаж
            days_until_stockout = float('inf')
            if avg_sales > 0.001 and stock > 0:
                days_until_stockout = stock / avg_sales
            
            # Определяем проблемы на основе метрик
            problems = []
            
            if stock > 0:
                if avg_sales < 0.001:
                    problems.append(f"⚠️ Товар на складе ({stock:.0f} шт), но НЕТ ПРОДАЖ за последние дни")
                elif days_until_stockout < 3:
                    problems.append(f"🔴 КРИТИЧНО: Закончится через {days_until_stockout:.0f} дней! (остаток: {stock:.0f} шт)")
                elif days_until_stockout < 7:
                    problems.append(f"⚠️ ВНИМАНИЕ: Закончится через {days_until_stockout:.0f} дней (остаток: {stock:.0f} шт)")
            else:
                problems.append(f"🔴 КРИТИЧНО: Товар отсутствует на складе!")
            
            if ctr < 3.0 and total_impressions > 100:
                problems.append(f"⚠️ Низкий CTR ({ctr:.1f}%) при {total_impressions} показах")
            
            # Добавляем в результат если есть остатки или реклама или проблемы
            if problems or total_spend > 0.001 or stock > 0:
                # Получаем стратегию из конфига
                strategy = self.config.get_strategy(product_id)
                
                return {
                    'ID': product_id,
                    'stock': stock,
                    'avg_sales': avg_sales,
                    'days_until_stockout': days_until_stockout,
                    'ctr': ctr,
                    'spend': total_spend,
                    'impressions': total_impressions,
                    'clicks': total_clicks,
                    'avg_cpc': avg_cpc,
                    'sales_dynamics': sales_dynamics,
                    'problems': problems,
                    'last_date': latest['дата'].strftime('%d.%m.%Y') if hasattr(latest['дата'], 'strftime') else str(latest['дата']),
                    'strategy': strategy.get('primary'),
                    'secondary_strategy': strategy.get('secondary')
                }
            return None
            
        except Exception as e:
            print(f"   ❌ Ошибка обработки {product_id}: {e}")
            return None
    
    def analyze_selected_products(self, products_df: pd.DataFrame, 
                                   ads_df: pd.DataFrame, 
                                   selected_articles: list) -> list:
        """
        Анализирует только выбранные товары
        
        Args:
            products_df: DataFrame с данными товаров
            ads_df: DataFrame с данными рекламы
            selected_articles: список артикулов для анализа
        
        Returns:
            список словарей с данными товаров
        """
        if products_df.empty:
            print("   ❌ Нет данных для анализа")
            return []
        
        print(f"\n🔍 Анализируем выбранные товары ({len(selected_articles)} шт)...")
        
        # Фильтруем только выбранные артикулы
        if 'ID' in products_df.columns:
            filtered_products = products_df[products_df['ID'].isin(selected_articles)]
        else:
            print("   ❌ В данных нет колонки 'ID'")
            return []
        
        if filtered_products.empty:
            print("   ❌ Нет данных по выбранным товарам")
            return []
        
        # Группируем по товарам
        product_ids = filtered_products['ID'].unique()
        product_groups = []
        
        for product_id in product_ids:
            product_data = filtered_products[filtered_products['ID'] == product_id]
            product_groups.append((product_id, product_data, ads_df))
        
        print(f"   Найдено данных по {len(product_groups)} товарам")
        
        if not product_groups:
            return []
        
        # Параллельная обработка (3 потока)
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(self.process_one_product, group) for group in product_groups]
            
            for i, future in enumerate(as_completed(futures)):
                result = future.result()
                if result:
                    results.append(result)
                if (i + 1) % 10 == 0:
                    print(f"   Обработано {i + 1}/{len(product_groups)} товаров...")
        
        print(f"   ✅ Найдено {len(results)} товаров с данными")
        return results
    
    def add_recommendations_batch(self, products_summary: list, max_items: int = 10, detailed: bool = False) -> list:
        """
        Добавляет AI-рекомендации для проблемных товаров
        
        Args:
            products_summary: список результатов анализа
            max_items: максимальное количество товаров для AI-рекомендаций
            detailed: если True, дает развернутые рекомендации
        
        Returns:
            обновленный список с рекомендациями
        """
        print("\n🤔 Получаем рекомендации от AI...")
        
        # Только товары с проблемами
        problem_products = [p for p in products_summary if p.get('problems')]
        
        if not problem_products:
            print("   ✅ Нет проблемных товаров")
            return products_summary
        
        # Сортируем по критичности
        def sort_key(p):
            score = 0
            for prob in p.get('problems', []):
                if '🔴' in prob:
                    score += 10
                elif '⚠️' in prob:
                    score += 5
            return -score
        
        problem_products.sort(key=sort_key)
        
        # Берем только топ-N
        top_problems = problem_products[:max_items]
        print(f"   Запрашиваем для {len(top_problems)} из {len(problem_products)} товаров...")
        
        # Параллельные запросы к AI
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            for product in top_problems:
                future = executor.submit(self.advisor.get_recommendation, product, detailed)
                futures[future] = product
            
            for future in as_completed(futures):
                product = futures[future]
                try:
                    recommendation = future.result(timeout=45 if detailed else 30)
                    product['recommendation'] = recommendation
                except Exception as e:
                    print(f"   ❌ Ошибка рекомендации для {product['ID']}: {e}")
                    product['recommendation'] = "⚠️ Рекомендация временно недоступна"
        
        return products_summary


# ============================================
# ТЕСТИРОВАНИЕ
# ============================================

if __name__ == "__main__":
    print("🚀 Тестирование быстрого анализатора...")
    start = time.time()
    
    try:
        analyzer = FastWBAnalyzer()
        
        # Тестируем получение всех артикулов
        all_articles = analyzer.get_all_articles()
        print(f"📋 Всего артикулов в таблице: {len(all_articles)}")
        if len(all_articles) > 0:
            print(f"   Первые 5: {all_articles[:5]}")
        
        # Загружаем данные за 7 дней
        products_df = analyzer.get_products_data(days=7)
        ads_df = analyzer.get_ads_data(days=7)
        
        # Тестовые артикулы (первые 3 из списка)
        test_articles = all_articles[:3] if all_articles else []
        
        if test_articles:
            results = analyzer.analyze_selected_products(products_df, ads_df, test_articles)
            results = analyzer.add_recommendations_batch(results, detailed=False)
            
            for r in results:
                print(f"\n📦 Товар {r['ID']}:")
                print(f"   Остаток (на {r['last_date']}): {r['stock']:.0f} шт")
                print(f"   Средние продажи (за 7 дней): {r['avg_sales']:.1f} шт/день")
                if r.get('problems'):
                    for p in r['problems']:
                        print(f"   {p}")
                if r.get('recommendation'):
                    print(f"   💡 {r['recommendation']}")
        
        elapsed = time.time() - start
        print(f"\n✅ Тест завершен за {elapsed:.1f} секунд")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()