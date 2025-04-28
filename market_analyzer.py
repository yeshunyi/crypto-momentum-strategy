#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
市场分析器模块，用于分析市场状态和板块轮动
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import time

from utils.logger import setup_logger

class MarketAnalyzer:
    """市场分析器类，用于分析市场状态和板块走势"""
    
    def __init__(self, config):
        """初始化市场分析器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("market_analyzer", logging.INFO)
        self.logger.info("初始化市场分析器...")
        
        # 引用数据提供器（会在初始化后设置）
        self.data_provider = None
        
        # 缓存
        self.market_state = None
        self.market_state_last_update = None
        self.sector_ranking = []
        self.sector_last_update = None
        
        # 板块列表
        self.sectors = ['DeFi', 'Layer2', 'AI', 'GameFi', 'Meme']
        
        self.logger.info("市场分析器初始化完成")
    
    def set_data_provider(self, data_provider):
        """设置数据提供器
        
        Args:
            data_provider: 数据提供器实例
        """
        self.data_provider = data_provider
    
    def assess_market_state(self):
        """评估市场状态
        
        Returns:
            str: 市场状态("strong_bull", "bull", "neutral", "bear", "strong_bear")
        """
        # 如果缓存有效，直接返回
        if (self.market_state is not None and 
            self.market_state_last_update is not None and 
            (datetime.now() - self.market_state_last_update).total_seconds() < self.config.market_state_refresh_interval):
            return self.market_state
        
        self.logger.info("评估市场状态...")
        
        try:
            # 检查数据提供器是否设置
            if self.data_provider is None:
                self.logger.error("数据提供器未设置，无法评估市场状态")
                return "neutral"  # 默认中性
                
            # 获取BTC数据
            btc_symbol = "BTC/USDT"
            btc_daily = self.data_provider.get_klines(btc_symbol, '1d', 20)
            
            if btc_daily is None or btc_daily.empty:
                self.logger.warning("无法获取BTC数据，无法评估市场状态")
                return "neutral"  # 默认中性
            
            # 计算BTC的简单移动平均线
            btc_daily['ma20'] = btc_daily['close'].rolling(window=20).mean()
            
            # 确保MA20有足够的数据点
            if btc_daily['ma20'].isna().tail(1).values[0]:
                self.logger.warning("MA20数据不足，使用所有可用数据")
                latest_ma20 = btc_daily['close'].mean()
            else:
                latest_ma20 = btc_daily['ma20'].iloc[-1]
                
            # 获取最新价格
            latest_close = btc_daily['close'].iloc[-1]
            
            # 计算最近5天的涨跌幅
            # 确保有足够的数据点
            if len(btc_daily) < 5:
                five_day_change = 0
                self.logger.warning("历史数据不足5天，无法计算5日涨跌幅")
            else:
                five_day_change = (latest_close / btc_daily['close'].iloc[-5] - 1) * 100
            
            # 计算ATR
            btc_atr = self.data_provider.calculate_atr(btc_symbol)
            if btc_atr is None:
                btc_atr = 4.0  # 使用默认值
                self.logger.warning("无法计算BTC ATR，使用默认值4.0%")
            
            # 评估市场状态
            if latest_close > latest_ma20 * 1.05 and five_day_change > 5:
                market_state = "strong_bull"
            elif latest_close > latest_ma20 and five_day_change > 0:
                market_state = "bull"
            elif latest_close < latest_ma20 * 0.95 and five_day_change < -5:
                market_state = "strong_bear"
            elif latest_close < latest_ma20 and five_day_change < 0:
                market_state = "bear"
            else:
                market_state = "neutral"
            
            self.logger.info(f"市场状态评估结果: {market_state}")
            
            # 更新缓存
            self.market_state = market_state
            self.market_state_last_update = datetime.now()
            
            return market_state
            
        except Exception as e:
            self.logger.error(f"评估市场状态出错: {str(e)}", exc_info=True)
            return "neutral"  # 默认中性
    
    def get_market_atr(self):
        """获取市场总体波动率(基于BTC)
        
        Returns:
            float: 市场ATR百分比
        """
        try:
            btc_atr = self.data_provider.calculate_atr("BTC/USDT")
            if btc_atr is None:
                return 4.0  # 默认中等波动率
            return btc_atr
        except Exception as e:
            self.logger.error(f"获取市场ATR出错: {str(e)}")
            return 4.0  # 默认中等波动率
    
    def determine_momentum_window(self):
        """根据市场波动确定涨速窗口
        
        Returns:
            tuple: (minutes_window, threshold_min, threshold_max)
        """
        market_atr = self.get_market_atr()
        
        # 根据ATR确定时间窗口和阈值
        if market_atr > 5.0:  # 高波动
            return 5, 3.0, 5.0
        elif market_atr >= 3.0:  # 中等波动
            return 10, 2.0, 3.0
        else:  # 低波动
            return 15, 1.5, 2.5
    
    def is_asian_trading_hour(self):
        """检查是否为亚洲交易时段
        
        Returns:
            bool: 是否为亚洲交易时段
        """
        current_hour = datetime.now().hour
        utc_hour = (current_hour - 8) % 24  # 假设本地时间是UTC+8
        return 3 <= utc_hour <= 5  # UTC 03:00-05:00
    
    def is_weekend(self):
        """检查是否为周末
        
        Returns:
            bool: 是否为周末
        """
        return datetime.now().weekday() >= 5  # 5和6代表周六和周日
    
    def adjust_threshold(self, base_threshold):
        """根据时段调整阈值
        
        Args:
            base_threshold: 基础阈值
            
        Returns:
            float: 调整后的阈值
        """
        if self.is_asian_trading_hour():
            return base_threshold + 0.5  # 亚洲时段提高阈值
        
        if self.is_weekend():
            return base_threshold - 0.3  # 周末降低阈值
            
        return base_threshold
    
    def rank_sectors(self):
        """对各个板块进行排名
        
        Returns:
            list: 排序后的板块列表
        """
        # 如果缓存有效，直接返回
        if (self.sector_ranking and 
            self.sector_last_update and 
            (datetime.now() - self.sector_last_update).total_seconds() < 3600):  # 1小时更新一次
            return self.sector_ranking
        
        self.logger.info("开始板块排名...")
        
        # 检查数据提供器是否已设置
        if self.data_provider is None:
            self.logger.error("数据提供器未设置，无法进行板块排名")
            return []
            
        sector_data = []
        
        try:
            # 设置超时保护
            start_time = time.time()
            max_processing_time = 60  # 最多处理60秒
            
            # 遍历所有板块
            for sector in self.sectors:
                # 检查是否超时
                if time.time() - start_time > max_processing_time:
                    self.logger.warning(f"板块排名处理超时，已完成 {len(sector_data)} 个板块")
                    break
                
                # 获取该板块的交易对
                symbols = self.data_provider.get_sector_symbols(sector)
                
                if not symbols:
                    self.logger.warning(f"板块 {sector} 没有找到交易对")
                    continue
                
                # 计算板块内币种的平均涨幅、最大涨幅、成交量增长率
                avg_change = 0
                max_change = 0
                volume_growth = 0
                valid_count = 0
                
                # 设置子任务超时保护
                sector_start_time = time.time()
                max_sector_time = 15  # 每个板块最多处理15秒
                
                for symbol in symbols[:min(10, len(symbols))]:  # 最多取10个代表性币种
                    # 检查板块处理是否超时
                    if time.time() - sector_start_time > max_sector_time:
                        self.logger.warning(f"板块 {sector} 处理超时，已处理 {valid_count} 个币种")
                        break
                        
                    try:
                        # 24小时涨跌幅
                        ticker = self.data_provider.get_ticker(symbol)
                        if ticker and 'percentage' in ticker:
                            change = ticker['percentage']
                            avg_change += change
                            max_change = max(max_change, change)
                            valid_count += 1
                        
                        # 成交量增长
                        volume_ratio = self.data_provider.get_volume_ratio(symbol)
                        if volume_ratio:
                            volume_growth += volume_ratio
                    except Exception as e:
                        self.logger.error(f"计算 {symbol} 数据出错: {str(e)}")
                
                if valid_count > 0:
                    avg_change /= valid_count
                    volume_growth /= valid_count
                    
                    # 计算板块得分
                    sector_score = (avg_change * 0.4) + (max_change * 0.3) + ((volume_growth - 1) * 30 * 0.3)
                    
                    sector_data.append({
                        'name': sector,
                        'avg_change': avg_change,
                        'max_change': max_change,
                        'volume_growth': volume_growth,
                        'score': sector_score
                    })
            
            # 按得分排序
            sorted_sectors = sorted(sector_data, key=lambda x: x['score'], reverse=True)
            
            self.logger.info(f"板块排名完成: {[s['name'] for s in sorted_sectors]}")
            
            # 更新缓存
            self.sector_ranking = sorted_sectors
            self.sector_last_update = datetime.now()
            
            return sorted_sectors
        
        except Exception as e:
            self.logger.error(f"板块排名出错: {str(e)}", exc_info=True)
            return []
    
    def get_top_sectors(self, count=3):
        """获取排名靠前的板块
        
        Args:
            count: 返回的板块数量
            
        Returns:
            list: 排名靠前的板块名称列表
        """
        sectors = self.rank_sectors()
        return [s['name'] for s in sectors[:count]]
    
    def get_social_media_momentum(self, symbol):
        """获取社交媒体热度
        
        Args:
            symbol: 交易对
            
        Returns:
            float: 社交媒体热度增长率，如果功能禁用则返回0
        """
        # 检查社交媒体功能是否启用
        if not self.config.social_api_enabled:
            self.logger.debug(f"社交媒体API功能已禁用，{symbol}社交热度返回0")
            return 0
            
        # 实际实现可能需要接入LunarCrush API或类似服务
        # 这里只是一个模拟实现
        try:
            # 从交易对获取币种名称
            if '/' in symbol:
                coin = symbol.split('/')[0]
            else:
                coin = symbol
                
            # 模拟一个API调用
            # 实际开发中，这里应该是一个真实的API调用
            """
            url = f"https://api.lunarcrush.com/v2?data=assets&symbol={coin}&key={self.config.lunarcrush_api_key}"
            response = requests.get(url)
            data = response.json()
            
            if 'data' in data and len(data['data']) > 0:
                asset = data['data'][0]
                return asset.get('twitter_volume_change_24h', 0)
            """
            
            # 模拟一个随机值
            import random
            return random.uniform(-50, 150)
            
        except Exception as e:
            self.logger.error(f"获取 {symbol} 社交媒体热度出错: {str(e)}")
            return 0
    
    def has_social_momentum(self, symbol, threshold=100):
        """检查是否有社交媒体热度
        
        Args:
            symbol: 交易对
            threshold: 热度增长阈值
            
        Returns:
            bool: 是否有足够的社交媒体热度
        """
        # 检查社交媒体功能是否启用
        if not self.config.social_api_enabled:
            return False
            
        growth_rate = self.get_social_media_momentum(symbol)
        return growth_rate > threshold 