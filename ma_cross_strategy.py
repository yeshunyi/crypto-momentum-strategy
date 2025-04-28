#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
均线交叉策略示例，演示如何使用买入日志和配置文件
"""

import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from order_executor import OrderExecutor
from config import Config
from data_fetcher import DataFetcher

class MACrossStrategy:
    """均线交叉策略类"""
    
    def __init__(self, config):
        """初始化策略
        
        Args:
            config: 配置对象
        """
        self.config = config
        # 初始化订单执行器
        self.order_executor = OrderExecutor(config)
        # 初始化数据获取器
        self.data_fetcher = DataFetcher(config)
        
        # 获取策略名称
        self.strategy_name = "ma_cross"
        
        # 检查策略是否启用
        if not config.is_strategy_enabled(self.strategy_name):
            raise ValueError(f"策略 {self.strategy_name} 未启用，请在配置文件中启用")
        
        # 从配置中读取参数
        self._load_parameters()
        
        # 记录上次检查时间，避免频繁检查
        self.last_check_time = datetime.now() - timedelta(hours=1)
        
        print(f"均线交叉策略初始化，交易对: {self.symbols}，短期均线: {self.short_window}，长期均线: {self.long_window}")
    
    def _load_parameters(self):
        """从配置中加载策略参数"""
        # 获取策略参数
        params = self.config.get_strategy_parameters(self.strategy_name)
        
        # 获取交易对
        self.symbols = self.config.get_strategy_symbols(self.strategy_name)
        if not self.symbols:
            raise ValueError(f"策略 {self.strategy_name} 未配置交易对")
        
        # 设置当前处理的交易对（可以循环处理多个）
        self.symbol = self.symbols[0]
        self.exchange_id = self.config.default_exchange
        
        # 策略参数
        self.short_window = params.get("short_window", 5)
        self.long_window = params.get("long_window", 20)
        self.timeframe = params.get("timeframe", "1h")
        
        # 仓位控制参数
        self.position_size = params.get("position_size", 0.1)
        self.max_positions = params.get("max_positions", 3)
        self.stop_loss_pct = params.get("stop_loss_pct", 3.0)
        
        # 回测时间范围
        days_back = params.get("days_back", 30)
        self.start_time = (datetime.now() - timedelta(days=days_back)).isoformat()
        self.end_time = datetime.now().isoformat()
        
        # 检查间隔
        self.check_interval = params.get("check_interval", 60)  # 默认60秒
        
        # 获利了结参数
        self.take_profit_pct = params.get("take_profit_pct", 5.0)
        
        # 移动止损参数
        self.trailing_stop = params.get("trailing_stop", False)
        self.trailing_stop_distance = params.get("trailing_stop_distance", 2.0)
        
        # 交易量过滤
        self.min_volume_usd = params.get("min_volume_usd", 1000000)  # 最小24小时成交量（美元）
        
        # 是否使用ichimoku云图
        self.use_ichimoku = params.get("use_ichimoku", False)
        if self.use_ichimoku:
            self.ichimoku_fast = params.get("ichimoku_fast", 9)
            self.ichimoku_slow = params.get("ichimoku_slow", 26)
            self.ichimoku_signal = params.get("ichimoku_signal", 52)
        
        # 每日最大交易次数
        self.max_trades_per_day = params.get("max_trades_per_day", 3)
    
    def load_trading_history(self):
        """加载交易历史记录"""
        print("加载交易历史记录...")
        
        # 获取交易历史
        history = self.order_executor.get_trading_history(
            symbol=self.symbol,
            exchange_id=self.exchange_id
        )
        
        self.entry_orders = history["entry_orders"]
        self.exit_orders = history["exit_orders"]
        self.stats = history["stats"]
        
        # 获取当前持仓
        self.active_positions = self.stats["active_positions"]
        
        # 输出统计信息
        print(f"历史买入订单数量: {len(self.entry_orders)}")
        print(f"历史卖出订单数量: {len(self.exit_orders)}")
        print(f"当前持仓数量: {len(self.active_positions)}")
        
        if len(self.exit_orders) > 0:
            print(f"历史胜率: {self.stats['win_rate']:.2f}%")
            print(f"平均收益率: {self.stats['avg_profit_percentage']:.2f}%")
            print(f"最大收益率: {self.stats['max_profit_percentage']:.2f}%")
            print(f"最大亏损率: {self.stats['max_loss_percentage']:.2f}%")
        
        # 处理移动止损
        if self.trailing_stop:
            self.trailing_stops = {}
            # 为每个活跃持仓设置初始移动止损
            for position in self.active_positions:
                if position['symbol'] == self.symbol:
                    entry_price = position['avg_price']
                    self.trailing_stops[position['order_id']] = entry_price * (1 - self.stop_loss_pct / 100)
                    print(f"设置初始移动止损: {position['symbol']}, 订单ID={position['order_id']}, 止损价={self.trailing_stops[position['order_id']]}")
    
    def get_market_data(self):
        """获取市场数据"""
        # 获取K线数据
        ohlcv = self.data_fetcher.fetch_ohlcv(
            symbol=self.symbol,
            timeframe=self.timeframe,
            limit=100  # 获取足够的历史数据计算均线
        )
        
        # 转换为DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        # 计算均线
        df['short_ma'] = df['close'].rolling(window=self.short_window).mean()
        df['long_ma'] = df['close'].rolling(window=self.long_window).mean()
        
        # 计算信号
        df['signal'] = 0
        # 短期均线上穿长期均线，买入信号
        df.loc[(df['short_ma'] > df['long_ma']) & (df['short_ma'].shift(1) <= df['long_ma'].shift(1)), 'signal'] = 1
        # 短期均线下穿长期均线，卖出信号
        df.loc[(df['short_ma'] < df['long_ma']) & (df['short_ma'].shift(1) >= df['long_ma'].shift(1)), 'signal'] = -1
        
        # 如果启用Ichimoku云图
        if self.use_ichimoku:
            # 计算基准线（Kijun-sen）
            df['kijun'] = (df['high'].rolling(window=self.ichimoku_slow).max() + df['low'].rolling(window=self.ichimoku_slow).min()) / 2
            # 计算转换线（Tenkan-sen）
            df['tenkan'] = (df['high'].rolling(window=self.ichimoku_fast).max() + df['low'].rolling(window=self.ichimoku_fast).min()) / 2
            # 计算先行带A（Senkou Span A）
            df['senkou_a'] = ((df['kijun'] + df['tenkan']) / 2).shift(self.ichimoku_slow)
            # 计算先行带B（Senkou Span B）
            df['senkou_b'] = ((df['high'].rolling(window=self.ichimoku_signal).max() + df['low'].rolling(window=self.ichimoku_signal).min()) / 2).shift(self.ichimoku_slow)
            # 滞后带（Chikou Span）
            df['chikou'] = df['close'].shift(-self.ichimoku_slow)
            
            # 额外的信号条件：价格在云图之上，且Tenkan线上穿Kijun线
            tenkan_cross = (df['tenkan'] > df['kijun']) & (df['tenkan'].shift(1) <= df['kijun'].shift(1))
            price_above_cloud = (df['close'] > df['senkou_a']) & (df['close'] > df['senkou_b'])
            
            # 结合Ichimoku信号和均线信号
            df.loc[tenkan_cross & price_above_cloud, 'signal'] = 1  # 买入信号增强
            
            # 价格跌破云图下方，强化卖出信号
            price_below_cloud = (df['close'] < df['senkou_a']) & (df['close'] < df['senkou_b'])
            df.loc[price_below_cloud, 'signal'] = -1  # 卖出信号
        
        return df
    
    def check_entry_conditions(self, df):
        """检查入场条件
        
        Args:
            df: 市场数据DataFrame
            
        Returns:
            bool: 是否满足入场条件
        """
        # 获取最新信号
        latest_signal = df['signal'].iloc[-1]
        
        # 检查是否有买入信号
        if latest_signal == 1:
            # 检查当前持仓数量是否已经达到最大值
            if len(self.active_positions) >= self.max_positions:
                print(f"当前持仓数量 {len(self.active_positions)} 已达到最大值 {self.max_positions}，不再买入")
                return False
            
            # 检查今日是否已有相同交易对的买入记录数量是否达到最大值
            today = datetime.now().strftime('%Y-%m-%d')
            today_entries = [order for order in self.entry_orders 
                            if order['symbol'] == self.symbol and 
                            order['timestamp'].startswith(today)]
            
            if len(today_entries) >= self.max_trades_per_day:
                print(f"今日 {self.symbol} 的买入记录已达到最大值 {self.max_trades_per_day}，不再买入")
                return False
            
            # 检查交易量
            if self.min_volume_usd > 0:
                # 获取24小时成交量
                ticker = self.data_fetcher.fetch_ticker(self.symbol, self.exchange_id)
                volume_usd = ticker.get('quoteVolume', 0)
                
                if volume_usd < self.min_volume_usd:
                    print(f"{self.symbol} 24小时成交量 ${volume_usd:.2f} 低于最小要求 ${self.min_volume_usd:.2f}，不买入")
                    return False
            
            return True
        
        return False
    
    def check_exit_conditions(self, df):
        """检查出场条件
        
        Args:
            df: 市场数据DataFrame
            
        Returns:
            list: 需要平仓的持仓列表
        """
        # 获取最新收盘价
        latest_price = df['close'].iloc[-1]
        
        # 获取最新信号
        latest_signal = df['signal'].iloc[-1]
        
        positions_to_exit = []
        
        # 检查每个持仓是否满足平仓条件
        for position in self.active_positions:
            # 仅处理当前交易对的持仓
            if position['symbol'] != self.symbol:
                continue
                
            entry_price = position['avg_price']
            order_id = position.get('order_id', '')
            
            # 计算当前收益率
            profit_pct = (latest_price - entry_price) / entry_price * 100
            
            # 更新移动止损
            if self.trailing_stop and order_id in self.trailing_stops:
                # 计算理论上的新止损价
                new_stop_price = latest_price * (1 - self.trailing_stop_distance / 100)
                
                # 如果新止损价高于当前止损价，则更新
                if new_stop_price > self.trailing_stops[order_id]:
                    old_stop = self.trailing_stops[order_id]
                    self.trailing_stops[order_id] = new_stop_price
                    print(f"更新移动止损: {position['symbol']}, 订单ID={order_id}, 止损价: {old_stop:.2f} -> {new_stop_price:.2f}")
            
            # 止损条件：价格低于止损价
            if self.trailing_stop and order_id in self.trailing_stops:
                if latest_price <= self.trailing_stops[order_id]:
                    positions_to_exit.append({
                        "position": position,
                        "reason": "trailing_stop",
                        "profit_pct": profit_pct
                    })
                    continue
            # 传统止损
            elif profit_pct <= -self.stop_loss_pct:
                positions_to_exit.append({
                    "position": position,
                    "reason": "stop_loss",
                    "profit_pct": profit_pct
                })
                continue
            
            # 获利了结条件
            if profit_pct >= self.take_profit_pct:
                positions_to_exit.append({
                    "position": position,
                    "reason": "take_profit",
                    "profit_pct": profit_pct
                })
                continue
            
            # 均线交叉卖出信号
            if latest_signal == -1:
                positions_to_exit.append({
                    "position": position,
                    "reason": "sell_signal",
                    "profit_pct": profit_pct
                })
        
        return positions_to_exit
    
    def execute_entry(self, df):
        """执行买入操作
        
        Args:
            df: 市场数据DataFrame
        """
        # 获取最新收盘价
        price = df['close'].iloc[-1]
        
        # 获取账户余额
        balance = self.get_balance()
        
        # 计算买入数量
        size = (balance * self.position_size) / price
        
        print(f"执行买入: {self.symbol}, 价格: {price}, 数量: {size:.6f}")
        
        # 执行买入
        result = self.order_executor.execute_entry(
            symbol=self.symbol,
            size=size,
            price=price,
            stage="ma_cross",
            exchange_id=self.exchange_id
        )
        
        if result["success"]:
            print(f"买入成功: 订单ID={result['order_id']}, 均价={result['avg_price']}")
            
            # 如果使用移动止损，设置初始止损价
            if self.trailing_stop:
                self.trailing_stops[result['order_id']] = result['avg_price'] * (1 - self.stop_loss_pct / 100)
                print(f"设置初始移动止损: {self.symbol}, 订单ID={result['order_id']}, 止损价={self.trailing_stops[result['order_id']]}")
            
            # 更新持仓记录
            self.load_trading_history()
        else:
            print(f"买入失败: {result['error']}")
    
    def execute_exit(self, position_to_exit):
        """执行卖出操作
        
        Args:
            position_to_exit: 需要平仓的持仓信息
        """
        position = position_to_exit["position"]
        reason = position_to_exit["reason"]
        profit_pct = position_to_exit["profit_pct"]
        
        # 获取最新收盘价
        df = self.get_market_data()
        price = df['close'].iloc[-1]
        
        size = position["size"]
        order_id = position.get("order_id", "")
        
        print(f"执行卖出: {self.symbol}, 价格: {price}, 数量: {size:.6f}, 原因: {reason}, 收益率: {profit_pct:.2f}%")
        
        # 执行卖出
        result = self.order_executor.execute_exit(
            symbol=self.symbol,
            size=size,
            price=price,
            reason=reason,
            exchange_id=self.exchange_id
        )
        
        if result["success"]:
            print(f"卖出成功: 订单ID={result['order_id']}, 均价={result['avg_price']}")
            
            # 如果使用移动止损，移除止损记录
            if self.trailing_stop and order_id in self.trailing_stops:
                del self.trailing_stops[order_id]
                print(f"移除移动止损记录: {self.symbol}, 订单ID={order_id}")
            
            # 更新持仓记录
            self.load_trading_history()
        else:
            print(f"卖出失败: {result['error']}")
    
    def get_balance(self):
        """获取账户余额"""
        # 这里简化处理，实际应该调用交易所API获取余额
        return 1000  # 假设有1000 USDT可用
    
    def run(self):
        """运行策略"""
        print(f"开始运行均线交叉策略... 参数: 短期均线={self.short_window}, 长期均线={self.long_window}, 时间周期={self.timeframe}")
        print(f"止损: {self.stop_loss_pct}%, 获利了结: {self.take_profit_pct}%, 移动止损: {'启用' if self.trailing_stop else '禁用'}")
        if self.use_ichimoku:
            print(f"启用Ichimoku云图参数: 快线={self.ichimoku_fast}, 慢线={self.ichimoku_slow}, 信号线={self.ichimoku_signal}")
        
        # 加载交易历史
        self.load_trading_history()
        
        while True:
            try:
                # 控制检查频率，避免频繁API调用
                current_time = datetime.now()
                if (current_time - self.last_check_time).seconds < self.check_interval:
                    time.sleep(1)
                    continue
                
                self.last_check_time = current_time
                
                # 获取市场数据
                df = self.get_market_data()
                
                # 检查是否有需要平仓的持仓
                positions_to_exit = self.check_exit_conditions(df)
                for position_to_exit in positions_to_exit:
                    self.execute_exit(position_to_exit)
                
                # 检查是否满足买入条件
                if self.check_entry_conditions(df):
                    self.execute_entry(df)
                
                # 打印当前持仓状态
                if self.active_positions:
                    print("\n当前持仓状态:")
                    latest_price = df['close'].iloc[-1]
                    for i, pos in enumerate(self.active_positions):
                        # 仅显示当前交易对的持仓
                        if pos['symbol'] != self.symbol:
                            continue
                            
                        entry_price = pos['avg_price']
                        profit_pct = (latest_price - entry_price) / entry_price * 100
                        
                        stop_info = ""
                        if self.trailing_stop and pos.get('order_id', '') in self.trailing_stops:
                            stop_price = self.trailing_stops[pos['order_id']]
                            stop_distance = (latest_price - stop_price) / latest_price * 100
                            stop_info = f", 移动止损价={stop_price:.2f} (距当前价{stop_distance:.2f}%)"
                        
                        print(f"{i+1}. {pos['symbol']}: 数量={pos['size']:.6f}, 买入价={entry_price}, 当前价={latest_price}, 收益率={profit_pct:.2f}%{stop_info}")
                
                print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 检查完成，等待下次检查...\n")
                
                time.sleep(10)  # 休息10秒
                
            except Exception as e:
                print(f"策略运行出错: {str(e)}")
                time.sleep(60)  # 出错后等待1分钟再重试

# 主函数
if __name__ == "__main__":
    # 加载配置
    config = Config()
    
    # 初始化并运行策略
    strategy = MACrossStrategy(config)
    strategy.run() 