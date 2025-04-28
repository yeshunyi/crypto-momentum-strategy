#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
市场数据提供模块，负责获取交易所数据
"""
import logging
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import ccxt
import threading

from utils.logger import setup_logger

class MarketDataProvider:
    """市场数据提供类，用于获取各种市场数据"""
    
    def __init__(self, config):
        """初始化数据提供器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("data_provider", logging.INFO)
        self.logger.info("初始化市场数据提供器...")
        
        # 初始化交易所API连接
        self.exchanges = {}
        for exchange_id in config.exchanges:
            self.logger.info(f"连接交易所: {exchange_id}")
            try:
                exchange_class = getattr(ccxt, exchange_id)
                self.exchanges[exchange_id] = exchange_class({
                    'apiKey': config.api_keys.get(exchange_id, {}).get('api_key', ''),
                    'secret': config.api_keys.get(exchange_id, {}).get('secret_key', ''),
                    'enableRateLimit': True,
                    'options': {'defaultType': 'spot'}
                })
            except Exception as e:
                self.logger.error(f"连接交易所 {exchange_id} 失败: {str(e)}")
        
        # 缓存数据
        self.market_data = {}  # 市场数据缓存
        self.symbols = {}  # 可交易币种缓存
        self.last_update = {}  # 最后更新时间
        
        # 增强型缓存，用于频繁计算的指标
        self.momentum_cache = {}  # 涨速缓存
        self.volume_ratio_cache = {}  # 量比缓存
        self.rsi_cache = {}  # RSI缓存
        self.atr_cache = {}  # ATR缓存
        self.sector_symbols_cache = {}  # 板块币种缓存
        self.cache_expiry = {}  # 缓存过期时间
        
        # 缓存锁，防止多线程访问问题
        self.cache_lock = threading.RLock()
        
        self.logger.info("市场数据提供器初始化完成")
    
    def init_data(self):
        """初始化数据，加载市场信息"""
        for exchange_id, exchange in self.exchanges.items():
            try:
                self.logger.info(f"加载 {exchange_id} 市场信息...")
                exchange.load_markets()
                self.symbols[exchange_id] = [s for s in exchange.symbols if self._is_valid_symbol(s)]
                self.logger.info(f"{exchange_id} 有效交易对: {len(self.symbols[exchange_id])}")
            except Exception as e:
                self.logger.error(f"加载 {exchange_id} 市场信息失败: {str(e)}")
    
    def _is_valid_symbol(self, symbol):
        """检查交易对是否有效
        
        Args:
            symbol: 交易对
            
        Returns:
            bool: 是否为有效交易对
        """
        # 排除杠杆交易、期权等非现货交易对
        if ':' in symbol or '/' not in symbol:
            return False
        
        # 过滤稳定币对稳定币的交易对
        base, quote = symbol.split('/')
        stablecoins = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 'GUSD']
        if base in stablecoins and quote in stablecoins:
            return False
        
        # 确保是以主流稳定币计价的交易对
        allowed_quotes = self.config.quote_currencies
        if quote not in allowed_quotes:
            return False
            
        return True
    
    def get_tradable_symbols(self, exchange_id=None):
        """获取可交易的币种列表
        
        Args:
            exchange_id: 交易所ID，如果为None则返回所有交易所
            
        Returns:
            list: 可交易的币种列表
        """
        if exchange_id:
            return self.symbols.get(exchange_id, [])
        
        all_symbols = []
        for symbols in self.symbols.values():
            all_symbols.extend(symbols)
        return all_symbols
    
    def get_klines(self, symbol, timeframe='5m', limit=100, exchange_id=None):
        """获取K线数据
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            limit: 获取数量
            exchange_id: 交易所ID
            
        Returns:
            pd.DataFrame: K线数据
        """
        try:
            exchange = self._get_exchange(exchange_id)
            if exchange is None:
                return None
            
            # 检查缓存
            if exchange_id is None:
                exchange_id = self.config.default_exchange
                
            cache_key = f"{exchange_id}_{symbol}_{timeframe}"
            current_time = time.time()
            
            # 如果缓存存在且未过期
            refresh_interval = self.config.data_refresh_interval
            if (cache_key in self.market_data and 
                cache_key in self.last_update and 
                current_time - self.last_update[cache_key] < refresh_interval):
                data = self.market_data[cache_key]
                # 如果缓存数据足够，直接返回
                if len(data) >= limit:
                    return data.tail(limit)
            
            # 设置超时和重试参数
            max_retries = 3
            retry_count = 0
            success = False
            ohlcv = None
            
            while not success and retry_count < max_retries:
                try:
                    # 设置超时时间
                    exchange.timeout = 10000  # 10秒超时
                    # 获取K线数据
                    self.logger.debug(f"获取 {symbol} {timeframe} K线数据 (尝试 {retry_count+1}/{max_retries})")
                    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                    success = True
                except Exception as e:
                    retry_count += 1
                    self.logger.warning(f"获取 {symbol} K线数据失败 (尝试 {retry_count}/{max_retries}): {str(e)}")
                    if retry_count < max_retries:
                        time.sleep(2)  # 休息2秒再重试
                    else:
                        raise  # 重试达到最大次数，抛出异常
            
            if not ohlcv or len(ohlcv) == 0:
                self.logger.warning(f"获取 {symbol} K线数据为空")
                return None
                
            # 转换为DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # 更新缓存
            self.market_data[cache_key] = df
            self.last_update[cache_key] = current_time
            
            return df
            
        except Exception as e:
            self.logger.error(f"获取 {symbol} K线数据出错: {str(e)}")
            return None
    
    def get_ticker(self, symbol, exchange_id=None):
        """获取当前行情
        
        Args:
            symbol: 交易对
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 行情数据
        """
        if exchange_id is None:
            exchange_id = self.config.default_exchange
            
        if exchange_id not in self.exchanges:
            self.logger.error(f"交易所 {exchange_id} 不存在")
            return None
            
        exchange = self.exchanges[exchange_id]
        
        try:
            return exchange.fetch_ticker(symbol)
        except Exception as e:
            self.logger.error(f"获取 {symbol} 行情数据失败: {str(e)}")
            return None
    
    def get_current_price(self, symbol, exchange_id=None):
        """获取当前价格
        
        Args:
            symbol: 交易对
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 当前价格
        """
        ticker = self.get_ticker(symbol, exchange_id)
        if ticker:
            return ticker['last']
        return None
    
    def get_historical_price(self, symbol, minutes_ago, exchange_id=None):
        """获取N分钟前的价格
        
        Args:
            symbol: 交易对
            minutes_ago: 多少分钟前
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 历史价格
        """
        # 确定合适的timeframe
        if minutes_ago <= 5:
            timeframe = '1m'
            limit = minutes_ago + 2
        elif minutes_ago <= 60:
            timeframe = '5m'
            limit = (minutes_ago // 5) + 2
        elif minutes_ago <= 240:
            timeframe = '15m'
            limit = (minutes_ago // 15) + 2
        else:
            timeframe = '1h'
            limit = (minutes_ago // 60) + 2
            
        limit = min(limit, 100)  # 避免请求过多数据
        
        df = self.get_klines(symbol, timeframe, limit, exchange_id)
        if df is None or df.empty:
            return None
            
        # 计算目标时间
        target_time = datetime.now() - timedelta(minutes=minutes_ago)
        
        # 找到最接近的时间点
        closest_time = min(df.index, key=lambda x: abs(x - target_time))
        return df.loc[closest_time, 'close']
    
    def calculate_momentum(self, symbol, minutes_window, exchange_id=None):
        """计算价格涨速
        
        Args:
            symbol: 交易对
            minutes_window: 时间窗口（分钟）
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 涨速（百分比）
        """
        try:
            # 检查缓存
            cache_key = f"{symbol}_{minutes_window}_momentum"
            current_time = time.time()
            
            # 使用缓存锁保护
            with self.cache_lock:
                if (cache_key in self.momentum_cache and 
                    current_time - self.cache_expiry.get(cache_key, 0) < 60):  # 60秒缓存
                    return self.momentum_cache[cache_key]
            
            # 确定时间周期
            if minutes_window <= 5:
                timeframe = '1m'
                limit = minutes_window + 5  # 获取额外数据点以确保有足够数据
            elif minutes_window <= 15:
                timeframe = '5m'
                limit = (minutes_window // 5) + 3
            elif minutes_window <= 60:
                timeframe = '15m'
                limit = (minutes_window // 15) + 3
            else:
                timeframe = '1h'
                limit = (minutes_window // 60) + 3
            
            # 获取K线数据
            df = self.get_klines(symbol, timeframe, limit, exchange_id)
            if df is None or len(df) < 2:
                return None
            
            # 确保是副本而非视图
            df = df.copy()
            
            # 获取当前价格和历史价格
            current_price = df['close'].iloc[-1]
            
            # 根据时间周期计算正确的历史索引
            if timeframe == '1m':
                hist_idx = min(minutes_window, len(df) - 1)
            elif timeframe == '5m':
                hist_idx = min(minutes_window // 5, len(df) - 1)
            elif timeframe == '15m':
                hist_idx = min(minutes_window // 15, len(df) - 1)
            else:  # 1h
                hist_idx = min(minutes_window // 60, len(df) - 1)
                
            # 防止索引越界
            if hist_idx <= 0:
                hist_idx = 1
                
            historical_price = df['close'].iloc[-hist_idx-1]
            
            # 计算涨速
            if historical_price > 0:
                momentum = ((current_price / historical_price) - 1) * 100
            else:
                momentum = 0
                
            # 更新缓存
            with self.cache_lock:
                self.momentum_cache[cache_key] = momentum
                self.cache_expiry[cache_key] = current_time
                
            return momentum
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} 涨速出错: {str(e)}")
            return None
    
    def get_volume_ratio(self, symbol, days=20, exchange_id=None):
        """获取成交量比率 (当前成交量/历史平均)
        
        Args:
            symbol: 交易对
            days: 历史天数
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 成交量比率
        """
        try:
            # 检查缓存
            cache_key = f"{symbol}_{days}_volume_ratio"
            current_time = time.time()
            
            # 使用缓存锁保护
            with self.cache_lock:
                if (cache_key in self.volume_ratio_cache and 
                    current_time - self.cache_expiry.get(cache_key, 0) < 300):  # 5分钟缓存
                    return self.volume_ratio_cache[cache_key]
            
            # 获取K线数据
            df = self.get_klines(symbol, '1d', limit=days+1, exchange_id=exchange_id)
            if df is None or len(df) < days // 2:  # 至少需要一半的数据才有效
                return None
                
            # 确保是副本而非视图
            df = df.copy()
            
            # 获取当前成交量和历史平均
            current_volume = df['volume'].iloc[-1]
            historical_volumes = df['volume'].iloc[:-1]
            
            if len(historical_volumes) == 0 or historical_volumes.mean() == 0:
                return None
                
            volume_ratio = current_volume / historical_volumes.mean()
            
            # 更新缓存
            with self.cache_lock:
                self.volume_ratio_cache[cache_key] = volume_ratio
                self.cache_expiry[cache_key] = current_time
                
            return volume_ratio
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} 成交量比率出错: {str(e)}")
            return None
    
    def get_previous_high(self, symbol, days=7, exchange_id=None):
        """获取前期高点
        
        Args:
            symbol: 交易对
            days: 查找天数，默认7天
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 前期高点价格
        """
        df = self.get_klines(symbol, '1d', days, exchange_id)
        if df is None or df.empty:
            return None
            
        return df['high'].max()
    
    def calculate_atr(self, symbol, period=14, exchange_id=None):
        """计算ATR (平均真实波幅)
        
        Args:
            symbol: 交易对
            period: 周期
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: ATR (百分比)
        """
        try:
            # 检查缓存
            cache_key = f"{symbol}_{period}_atr"
            current_time = time.time()
            if (cache_key in self.market_data and 
                cache_key in self.last_update and 
                current_time - self.last_update[cache_key] < self.config.data_refresh_interval):
                return self.market_data[cache_key]
                
            # 获取K线数据
            df = self.get_klines(symbol, '1d', limit=period*2, exchange_id=exchange_id)
            if df is None or len(df) < period:
                return None
                
            # 创建明确的副本以避免警告
            df = df.copy()
            
            # 使用loc进行赋值，避免SettingWithCopyWarning
            df.loc[:, 'tr0'] = df['high'] - df['low']
            df.loc[:, 'tr1'] = abs(df['high'] - df['close'].shift(1))
            df.loc[:, 'tr2'] = abs(df['low'] - df['close'].shift(1))
            df.loc[:, 'tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
            df.loc[:, 'atr'] = df['tr'].rolling(period).mean()
            
            # 计算最新的ATR (百分比)
            latest_close = df['close'].iloc[-1]
            latest_atr = df['atr'].iloc[-1]
            
            if pd.isna(latest_atr) or latest_close == 0:
                return None
                
            atr_pct = (latest_atr / latest_close) * 100
            
            # 更新缓存
            self.market_data[cache_key] = atr_pct
            self.last_update[cache_key] = current_time
            
            return atr_pct
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} ATR出错: {str(e)}")
            return None
    
    def calculate_rsi(self, symbol, period=14, timeframe='1h', exchange_id=None):
        """计算RSI (相对强弱指数)
        
        Args:
            symbol: 交易对
            period: 周期
            timeframe: 时间周期
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: RSI值
        """
        try:
            # 检查缓存
            cache_key = f"{symbol}_{timeframe}_{period}_rsi"
            current_time = time.time()
            if (cache_key in self.market_data and 
                cache_key in self.last_update and 
                current_time - self.last_update[cache_key] < self.config.data_refresh_interval):
                return self.market_data[cache_key]
                
            # 获取K线数据
            df = self.get_klines(symbol, timeframe, limit=period*3, exchange_id=exchange_id)
            if df is None or len(df) < period + 1:
                return None
                
            # 创建明确的副本以避免警告
            df = df.copy()
            
            # 计算价格变化
            df.loc[:, 'change'] = df['close'].diff()
            
            # 分离上涨和下跌
            df.loc[:, 'gain'] = df['change'].clip(lower=0)
            df.loc[:, 'loss'] = -df['change'].clip(upper=0)
            
            # 计算平均上涨和下跌
            df.loc[:, 'avg_gain'] = df['gain'].rolling(window=period).mean()
            df.loc[:, 'avg_loss'] = df['loss'].rolling(window=period).mean()
            
            # 计算相对强度
            df.loc[:, 'rs'] = df['avg_gain'] / df['avg_loss'].replace(0, 1e-10)  # 避免除以零错误
            
            # 计算RSI
            df.loc[:, 'rsi'] = 100 - (100 / (1 + df['rs']))
            
            # 获取最新的RSI值
            rsi = df['rsi'].iloc[-1]
            
            if pd.isna(rsi):
                return None
                
            # 更新缓存
            self.market_data[cache_key] = rsi
            self.last_update[cache_key] = current_time
                
            return rsi
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} RSI出错: {str(e)}")
            return None
    
    def get_sector_symbols(self, sector, exchange_id=None):
        """获取特定板块的币种
        
        Args:
            sector: 板块名称
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            list: 该板块下的币种列表
        """
        # 这里应该根据实际情况实现，可能需要外部数据源
        # 这只是一个简单的示例
        sector_mapping = {
            'DeFi': ['UNI/', 'AAVE/', 'COMP/', 'SUSHI/', 'YFI/', 'CAKE/', 'CRV/'],
            'Layer2': ['MATIC/', 'ARB/', 'OP/', 'IMX/', 'ZK/', 'METIS/', 'SCROLL/'],
            'AI': ['FET/', 'OCEAN/', 'RNDR/', 'GRT/', 'AGIX/', 'NMR/'],
            'GameFi': ['AXS/', 'SAND/', 'MANA/', 'ENJ/', 'GALA/', 'ILV/', 'MAGIC/'],
            'Meme': ['DOGE/', 'SHIB/', 'PEPE/', 'FLOKI/', 'BONK/', 'WIF/']
        }
        
        if sector not in sector_mapping:
            return []
            
        all_symbols = self.get_tradable_symbols(exchange_id)
        sector_symbols = []
        
        for prefix in sector_mapping[sector]:
            sector_symbols.extend([s for s in all_symbols if s.startswith(prefix)])
            
        return sector_symbols
    
    def get_max_drawdown(self, symbol, days=7, exchange_id=None):
        """计算最大回撤
        
        Args:
            symbol: 交易对
            days: 计算周期（天）
            exchange_id: 交易所ID
            
        Returns:
            float: 最大回撤（百分比）
        """
        try:
            # 获取日K线数据
            df = self.get_klines(symbol, '1d', days, exchange_id)
            
            if df is None or df.empty:
                return None
            
            # 创建DataFrame的副本以避免SettingWithCopyWarning
            df_copy = df.copy()
            
            # 使用正确的方式计算最大回撤
            df_copy.loc[:, 'roll_max'] = df_copy['close'].cummax()
            df_copy.loc[:, 'drawdown'] = (df_copy['roll_max'] - df_copy['close']) / df_copy['roll_max'] * 100
            
            # 获取最大回撤
            max_drawdown = df_copy['drawdown'].max()
            
            return max_drawdown
            
        except Exception as e:
            self.logger.error(f"计算 {symbol} 最大回撤出错: {str(e)}")
            return None
    
    def get_trading_volume(self, symbol, days=30, exchange_id=None):
        """获取交易量
        
        Args:
            symbol: 交易对
            days: 天数
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            float: 总交易量（以美元计）
        """
        df = self.get_klines(symbol, '1d', days, exchange_id)
        if df is None or df.empty:
            return None
            
        # 简单估算美元交易量
        volume_usd = (df['close'] * df['volume']).sum()
        
        return volume_usd
    
    def _get_exchange(self, exchange_id=None):
        """获取交易所实例
        
        Args:
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            交易所实例
        """
        if exchange_id is None:
            exchange_id = self.config.default_exchange
            
        if exchange_id not in self.exchanges:
            self.logger.error(f"交易所 {exchange_id} 不存在")
            return None
            
        return self.exchanges[exchange_id] 