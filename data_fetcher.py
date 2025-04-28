#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据获取模块，负责从交易所获取市场数据
"""
import logging
import time
from datetime import datetime, timedelta

from utils.logger import setup_logger

class DataFetcher:
    """数据获取器类，负责从交易所获取市场数据"""
    
    def __init__(self, config):
        """初始化数据获取器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("data_fetcher", logging.INFO)
        self.logger.info("初始化数据获取器...")
        
        # 获取交易所连接
        from order_executor import OrderExecutor
        order_executor = OrderExecutor(config)
        self.exchanges = order_executor.exchanges
        self.default_exchange = config.default_exchange
        
        # 缓存，避免频繁请求同样的数据
        self.cache = {}
        self.cache_expiry = 60  # 缓存有效期（秒）
        
        self.logger.info("数据获取器初始化完成")
    
    def fetch_ohlcv(self, symbol, timeframe='1h', limit=100, since=None, exchange_id=None):
        """获取K线数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            limit: 获取数量
            since: 开始时间戳（毫秒）
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            list: K线数据列表
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return []
            
        exchange = self.exchanges[exchange_id]
        
        # 构建缓存键
        cache_key = f"{exchange_id}_{symbol}_{timeframe}_{limit}_{since}"
        
        # 检查缓存
        now = time.time()
        if cache_key in self.cache:
            cache_data, cache_time = self.cache[cache_key]
            # 如果缓存未过期，直接返回缓存数据
            if now - cache_time < self.cache_expiry:
                self.logger.debug(f"使用缓存数据: {cache_key}")
                return cache_data
        
        self.logger.info(f"获取 {symbol} 的K线数据，时间周期: {timeframe}, 数量: {limit}")
        
        try:
            # 加载市场
            exchange.load_markets()
            
            # 获取K线数据
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            
            # 更新缓存
            self.cache[cache_key] = (ohlcv, now)
            
            self.logger.info(f"获取到 {len(ohlcv)} 条K线数据")
            
            return ohlcv
            
        except Exception as e:
            error_msg = f"获取K线数据失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return []
    
    def fetch_ticker(self, symbol, exchange_id=None):
        """获取行情数据
        
        Args:
            symbol: 交易对
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 行情数据
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {}
            
        exchange = self.exchanges[exchange_id]
        
        # 构建缓存键
        cache_key = f"{exchange_id}_{symbol}_ticker"
        
        # 检查缓存
        now = time.time()
        if cache_key in self.cache:
            cache_data, cache_time = self.cache[cache_key]
            # 如果缓存未过期（10秒内），直接返回缓存数据
            if now - cache_time < 10:  # 行情数据缓存时间较短
                self.logger.debug(f"使用缓存数据: {cache_key}")
                return cache_data
        
        self.logger.info(f"获取 {symbol} 的行情数据")
        
        try:
            # 获取行情数据
            ticker = exchange.fetch_ticker(symbol)
            
            # 更新缓存
            self.cache[cache_key] = (ticker, now)
            
            return ticker
            
        except Exception as e:
            error_msg = f"获取行情数据失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {}
    
    def fetch_orderbook(self, symbol, limit=20, exchange_id=None):
        """获取订单簿数据
        
        Args:
            symbol: 交易对
            limit: 获取深度
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单簿数据
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {}
            
        exchange = self.exchanges[exchange_id]
        
        # 构建缓存键
        cache_key = f"{exchange_id}_{symbol}_orderbook_{limit}"
        
        # 检查缓存
        now = time.time()
        if cache_key in self.cache:
            cache_data, cache_time = self.cache[cache_key]
            # 如果缓存未过期（5秒内），直接返回缓存数据
            if now - cache_time < 5:  # 订单簿数据缓存时间更短
                self.logger.debug(f"使用缓存数据: {cache_key}")
                return cache_data
        
        self.logger.info(f"获取 {symbol} 的订单簿数据，深度: {limit}")
        
        try:
            # 获取订单簿数据
            orderbook = exchange.fetch_order_book(symbol, limit)
            
            # 更新缓存
            self.cache[cache_key] = (orderbook, now)
            
            return orderbook
            
        except Exception as e:
            error_msg = f"获取订单簿数据失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {} 