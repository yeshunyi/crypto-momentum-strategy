#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
信号生成器模块，负责基于市场数据生成交易信号
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime
import time

from utils.logger import setup_logger

class SignalGenerator:
    """信号生成器类，根据市场数据生成交易信号"""
    
    def __init__(self, config, market_analyzer):
        """初始化信号生成器
        
        Args:
            config: 配置对象
            market_analyzer: 市场分析器对象
        """
        self.config = config
        self.market_analyzer = market_analyzer
        self.logger = setup_logger("signal_generator", logging.INFO)
        self.logger.info("初始化信号生成器...")
        
        # 引用数据提供器（由策略主类传入）
        self.data_provider = None
        
        self.logger.info("信号生成器初始化完成")
    
    def set_data_provider(self, data_provider):
        """设置数据提供器
        
        Args:
            data_provider: 数据提供器实例
        """
        self.data_provider = data_provider
        # 同时设置市场分析器的数据提供器
        self.market_analyzer.set_data_provider(data_provider)
    
    def generate_signals(self, symbols):
        """生成交易信号
        
        Args:
            symbols: 交易对列表
            
        Returns:
            list: 交易信号列表
        """
        self.logger.info(f"开始生成交易信号，共{len(symbols)}个交易对...")
        signals = []
        
        # 获取市场状态
        market_state = self.market_analyzer.assess_market_state()
        
        # 获取热门板块
        top_sectors = self.market_analyzer.get_top_sectors(3)
        
        # 确定涨速阈值窗口
        minutes_window, threshold_min, threshold_max = self.market_analyzer.determine_momentum_window()
        # 调整阈值
        adjusted_threshold = self.market_analyzer.adjust_threshold(threshold_min)
        
        self.logger.info(f"市场环境: {market_state}, 热门板块: {top_sectors}, 涨速窗口: {minutes_window}分钟, 阈值: {adjusted_threshold}%")
        
        # 分批处理，每50个币种一批
        batch_size = 50
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        processed_count = 0
        signal_count = 0
        
        start_time = time.time()
        
        for batch_idx in range(total_batches):
            batch_start = batch_idx * batch_size
            batch_end = min(batch_start + batch_size, len(symbols))
            batch = symbols[batch_start:batch_end]
            
            self.logger.debug(f"处理批次 {batch_idx+1}/{total_batches}，包含 {len(batch)} 个交易对")
            
            # 处理当前批次的币种
            for symbol in batch:
                try:
                    # 获取涨速
                    momentum = self.data_provider.calculate_momentum(symbol, minutes_window)
                    if momentum is None or momentum < adjusted_threshold:
                        continue
                        
                    # 获取成交量比例
                    volume_ratio = self.data_provider.get_volume_ratio(symbol)
                    if volume_ratio is None or volume_ratio < 1.5:
                        continue
                        
                    # 获取RSI
                    rsi = self.data_provider.calculate_rsi(symbol)
                    if rsi is None or rsi > 75:  # 超买过滤
                        continue
                    
                    # 获取当前价格
                    current_price = self.data_provider.get_current_price(symbol)
                    if current_price is None:
                        continue
                        
                    # 获取ATR
                    atr = self.data_provider.calculate_atr(symbol)
                    if atr is None:
                        atr = 4.0  # 默认值
                    
                    # 计算目标利润 (ATR的1.5倍)
                    profit_target = min(atr * 1.5 / 100, 0.1)  # 最大10%
                    
                    # 确定所属板块
                    symbol_sector = None
                    for sector in top_sectors:
                        if symbol in self.data_provider.get_sector_symbols(sector):
                            symbol_sector = sector
                            break
                    
                    # 计算信号评分
                    score = self._calculate_signal_score(momentum, volume_ratio, rsi, atr, symbol_sector in top_sectors)
                    
                    # 生成信号
                    signal = {
                        'symbol': symbol,
                        'momentum': momentum,
                        'volume_ratio': volume_ratio,
                        'rsi': rsi,
                        'entry_price': current_price,
                        'atr': atr,
                        'profit_target': profit_target,
                        'sector': symbol_sector,
                        'score': score,
                        'market_state': market_state,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    signals.append(signal)
                    signal_count += 1
                    
                except Exception as e:
                    self.logger.error(f"处理交易对 {symbol} 出错: {str(e)}")
                
                processed_count += 1
                
                # 每处理50个币种，显示一次进度
                if processed_count % 50 == 0:
                    elapsed_time = time.time() - start_time
                    progress_pct = processed_count / len(symbols) * 100
                    estimated_total = elapsed_time / (processed_count / len(symbols))
                    remaining_time = max(0, estimated_total - elapsed_time)
                    
                    self.logger.info(
                        f"信号生成进度: {processed_count}/{len(symbols)} ({progress_pct:.1f}%) "
                        f"已发现信号: {signal_count} "
                        f"预计剩余时间: {remaining_time:.1f}秒"
                    )
        
        elapsed_time = time.time() - start_time
        self.logger.info(f"信号生成完成，共处理 {len(symbols)} 个交易对，生成 {len(signals)} 个信号，耗时 {elapsed_time:.1f}秒")
        
        # 按评分排序
        sorted_signals = sorted(signals, key=lambda x: x['score'], reverse=True)
        
        return sorted_signals
    
    def _calculate_signal_score(self, momentum, volume_ratio, rsi, atr, in_top_sector):
        """计算信号评分
        
        Args:
            momentum: 涨速
            volume_ratio: 量比
            rsi: RSI
            atr: ATR
            in_top_sector: 是否在热门板块
            
        Returns:
            float: 信号得分
        """
        score = 0
        
        # 1. 涨速得分 (0-40分)
        momentum_score = min(momentum / 10 * 40, 40)
        score += momentum_score
        
        # 2. 量比得分 (0-25分)
        volume_score = min((volume_ratio - 1) * 12.5, 25)
        score += volume_score
        
        # 3. 板块得分 (0/15分)
        if in_top_sector:
            score += 15
        
        # 4. RSI得分 (0-10分)
        # RSI在40-60之间最佳，过高过低都降低分数
        if rsi is not None:
            if 40 <= rsi <= 60:
                score += 10
            elif (30 <= rsi < 40) or (60 < rsi <= 70):
                score += 5
            else:
                score += 0
        
        return score 