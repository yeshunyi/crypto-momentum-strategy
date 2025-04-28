#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
风险管理器模块，负责风险控制和仓位管理
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

from utils.logger import setup_logger

class RiskManager:
    """风险管理器类，负责风险控制和仓位管理"""
    
    def __init__(self, config):
        """初始化风险管理器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("risk_manager", logging.INFO)
        self.logger.info("初始化风险管理器...")
        
        # 引用数据提供器（由策略主类传入）
        self.data_provider = None
        
        # 风险参数
        self.max_risk_per_trade = config.max_risk_per_trade  # 单笔风险敞口
        self.max_total_risk = config.max_total_risk  # 总风险敞口
        self.max_sector_allocation = config.max_sector_allocation  # 单一板块最大占比
        
        # 持仓和风险状态
        self.current_positions = {}  # 当前持仓
        self.current_risk = 0.0  # 当前风险
        self.sector_allocation = {}  # 各板块持仓
        
        # 黑名单
        self.blacklist = set()
        
        self.logger.info("风险管理器初始化完成")
    
    def set_data_provider(self, data_provider):
        """设置数据提供器
        
        Args:
            data_provider: 数据提供器实例
        """
        self.data_provider = data_provider
    
    def update_blacklist(self):
        """更新黑名单
        
        Returns:
            set: 更新后的黑名单
        """
        self.logger.info("更新币种黑名单...")
        
        # 检查数据提供器是否已设置
        if self.data_provider is None:
            self.logger.error("数据提供器未设置，无法更新黑名单")
            return self.blacklist
            
        try:
            # 清空原黑名单
            new_blacklist = set()
            
            # 获取所有币种
            symbols = self.data_provider.get_tradable_symbols()
            
            # 设置超时保护
            start_time = time.time()
            max_processing_time = 120  # 最多处理120秒
            
            # 使用分批处理，避免一次处理过多
            batch_size = 20
            max_batches = min(5, len(symbols) // batch_size + 1)  # 限制批次数量，最多处理5批
            self.logger.info(f"将处理前 {max_batches * batch_size} 个币种（共 {len(symbols)} 个）")
            
            for i in range(0, min(max_batches * batch_size, len(symbols)), batch_size):
                # 检查是否超时
                if time.time() - start_time > max_processing_time:
                    self.logger.warning(f"黑名单更新处理超时，已完成 {i} 个币种的处理")
                    break
                    
                batch = symbols[i:i+batch_size]
                self.logger.debug(f"处理黑名单批次 {i//batch_size + 1}/{max_batches}，共{len(batch)}个币种")
                
                for symbol in batch:
                    try:
                        if self._check_blacklist_conditions(symbol):
                            new_blacklist.add(symbol)
                    except Exception as e:
                        self.logger.error(f"检查 {symbol} 黑名单条件出错: {str(e)}")
                
                # 批次处理后稍等一下，避免API请求过于频繁
                if i + batch_size < len(symbols) and i + batch_size < max_batches * batch_size:
                    time.sleep(1)
            
            # 更新黑名单
            self.blacklist = new_blacklist
            self.logger.info(f"黑名单更新完成，共 {len(self.blacklist)} 个币种")
            
            return self.blacklist
            
        except Exception as e:
            self.logger.error(f"更新黑名单出错: {str(e)}", exc_info=True)
            return self.blacklist
    
    def check_market_risk(self):
        """检查市场整体风险
        
        Returns:
            bool: 是否允许交易
        """
        try:
            # 检查数据提供器是否已设置
            if self.data_provider is None:
                self.logger.error("数据提供器未设置，无法检查市场风险")
                return True  # 默认允许交易
                
            # 获取BTC的ATR
            btc_atr = self.data_provider.calculate_atr("BTC/USDT")
            
            # 如果ATR超过阈值，认为风险过高
            if btc_atr is not None and btc_atr > 7:
                self.logger.warning(f"市场ATR为 {btc_atr:.2f}%，超过风险阈值7%")
                return False
            
            # 这里可以添加其他市场风险检查逻辑
            
            return True
            
        except Exception as e:
            self.logger.error(f"检查市场风险出错: {str(e)}")
            return True  # 默认允许交易
    
    def filter_signals(self, signals):
        """过滤交易信号
        
        Args:
            signals: 原始信号列表
            
        Returns:
            list: 过滤后的信号列表
        """
        filtered = []
        
        for signal in signals:
            symbol = signal['symbol']
            
            # 黑名单检查
            if symbol in self.blacklist:
                self.logger.debug(f"过滤 {symbol}: 在黑名单中")
                continue
            
            # RSI超买检查
            if signal['rsi'] is not None and signal['rsi'] > 75:
                self.logger.debug(f"过滤 {symbol}: RSI {signal['rsi']:.2f} > 75，超买状态")
                continue
            
            # 检查是否已经有持仓
            if symbol in self.current_positions:
                self.logger.debug(f"过滤 {symbol}: 已有持仓")
                continue
            
            # 通过所有检查，保留该信号
            filtered.append(signal)
        
        self.logger.info(f"信号过滤：原始 {len(signals)} 个，过滤后 {len(filtered)} 个")
        return filtered
    
    def rank_signals(self, signals):
        """对过滤后的信号进行排序
        
        Args:
            signals: 过滤后的信号列表
            
        Returns:
            list: 排序后的信号列表
        """
        # 已经在信号生成阶段进行了评分和排序
        # 这里可以添加额外的排序逻辑
        return signals
    
    def can_open_position(self, signal):
        """检查是否可以开仓
        
        Args:
            signal: 交易信号
            
        Returns:
            bool: 是否可以开仓
        """
        # 检查总风险
        if self.current_risk + self.max_risk_per_trade > self.max_total_risk:
            self.logger.warning(f"拒绝 {signal['symbol']} 开仓: 总风险 {self.current_risk:.2f}% 接近上限 {self.max_total_risk}%")
            return False
        
        # 检查板块集中度
        sector = signal['sector']
        if sector:
            current_sector_allocation = self.sector_allocation.get(sector, 0)
            if current_sector_allocation + self.max_risk_per_trade > self.max_sector_allocation * self.max_total_risk:
                self.logger.warning(f"拒绝 {signal['symbol']} 开仓: {sector} 板块持仓 {current_sector_allocation:.2f}% 接近上限")
                return False
        
        # 根据市场状态调整
        market_state = signal['market_state']
        if market_state in ["bear", "strong_bear"]:
            # 熊市条件更严格
            if signal['score'] < 70:  # 要求更高的信号质量
                self.logger.warning(f"拒绝 {signal['symbol']} 开仓: 熊市环境下信号评分 {signal['score']:.2f} 不足")
                return False
        
        return True
    
    def calculate_position_size(self, signal):
        """计算仓位大小
        
        Args:
            signal: 交易信号
            
        Returns:
            float: 仓位大小（基础货币数量）
        """
        # 获取账户余额
        account_balance = self.config.account_balance
        
        # 基础风险金额
        risk_amount = account_balance * (self.max_risk_per_trade / 100)
        
        # 根据信号得分调整仓位
        score_factor = min(signal['score'] / 60, 1.0)  # 60分以上为满分
        adjusted_risk = risk_amount * score_factor
        
        # 根据市场状态调整
        market_state = signal['market_state']
        if market_state == "strong_bull":
            adjusted_risk *= 1.2  # 强势牛市增加仓位
        elif market_state == "bear":
            adjusted_risk *= 0.7  # 熊市减少仓位
        elif market_state == "strong_bear":
            adjusted_risk *= 0.5  # 强势熊市大幅减少仓位
        
        # 计算止损点位（2%）
        stop_loss_pct = 0.02
        
        # 计算可买入金额
        position_value = adjusted_risk / stop_loss_pct
        
        # 计算币数量
        price = signal['entry_price']
        position_size = position_value / price
        
        self.logger.info(f"{signal['symbol']} 仓位计算: 风险 ${adjusted_risk:.2f}, 仓位 ${position_value:.2f}, 数量 {position_size:.6f}")
        
        # 更新风险记录
        self.current_risk += self.max_risk_per_trade
        if signal['sector']:
            self.sector_allocation[signal['sector']] = self.sector_allocation.get(signal['sector'], 0) + self.max_risk_per_trade
        
        return position_size
    
    def update_position(self, symbol, action, size=None):
        """更新持仓和风险记录
        
        Args:
            symbol: 交易对
            action: 操作类型（"open", "close", "partial_close"）
            size: 平仓数量（仅在部分平仓时需要）
        """
        if action == "open":
            # 已在calculate_position_size中更新风险记录
            self.current_positions[symbol] = True
            
        elif action == "close":
            # 完全平仓
            if symbol in self.current_positions:
                del self.current_positions[symbol]
                
                # 更新风险记录
                self.current_risk -= self.max_risk_per_trade
                
                # 更新板块分配
                for sector, allocation in self.sector_allocation.items():
                    # 这里简化处理，实际应该记录每个持仓的板块
                    self.sector_allocation[sector] -= self.max_risk_per_trade / len(self.current_positions)
                
        elif action == "partial_close" and size is not None:
            # 部分平仓，只更新风险记录
            ratio = size / self.position_sizes.get(symbol, 1)
            self.current_risk -= self.max_risk_per_trade * ratio
            
            # 更新板块分配
            for sector, allocation in self.sector_allocation.items():
                self.sector_allocation[sector] -= self.max_risk_per_trade * ratio / len(self.current_positions)
    
    def _check_blacklist_conditions(self, symbol):
        """检查单个币种是否应该被加入黑名单
        
        Args:
            symbol: 交易对
            
        Returns:
            bool: 是否应该加入黑名单
        """
        try:
            # 检查数据提供器是否已设置
            if self.data_provider is None:
                return False
                
            # 检查最大回撤
            max_drawdown = self.data_provider.get_max_drawdown(symbol, days=7)
            if max_drawdown is not None and max_drawdown > 25:
                self.logger.debug(f"{symbol} 加入黑名单：7日最大回撤 {max_drawdown:.2f}% > 25%")
                return True
            
            # 检查交易量
            volume = self.data_provider.get_trading_volume(symbol, days=30)
            if volume is not None and volume < 1000000:
                self.logger.debug(f"{symbol} 加入黑名单：30日交易量 ${volume:.2f} < $1,000,000")
                return True
            
            # 这里可以添加其他检查条件
            
            return False
        except Exception as e:
            self.logger.error(f"检查 {symbol} 黑名单条件出错: {str(e)}")
            return False 