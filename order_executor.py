#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
订单执行器模块，负责交易执行
"""
import logging
import time
import random
import json
import os
from datetime import datetime
import ccxt
import math

from utils.logger import setup_logger

class OrderExecutor:
    """订单执行器类，负责执行交易订单"""
    
    def __init__(self, config):
        """初始化订单执行器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("order_executor", logging.INFO)
        self.logger.info("初始化订单执行器...")
        
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
                # 如果有额外选项，可以在这里设置
                if hasattr(self.exchanges[exchange_id], 'set_sandbox_mode') and config.test_mode:
                    self.exchanges[exchange_id].set_sandbox_mode(True)
                    self.logger.info(f"{exchange_id} 设置为测试模式")
            except Exception as e:
                self.logger.error(f"连接交易所 {exchange_id} 失败: {str(e)}")
        
        # 默认交易所
        self.default_exchange = config.default_exchange
        
        # 日志目录
        self.log_dir = config.log_dir if hasattr(config, 'log_dir') else 'logs'
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 买入日志文件路径
        self.entry_log_file = os.path.join(self.log_dir, 'entry_orders.json')
        
        self.logger.info("订单执行器初始化完成")
    
    def execute_entry(self, symbol, size, price, stage, exchange_id=None):
        """执行买入订单
        
        Args:
            symbol: 交易对
            size: 买入数量
            price: 买入价格
            stage: 入场阶段
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单结果
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
        exchange = self.exchanges[exchange_id]
        
        # 确保交易对存在
        try:
            exchange.load_markets()
            if symbol not in exchange.symbols:
                error_msg = f"{symbol} 在交易所 {exchange_id} 中不存在"
                self.logger.error(error_msg)
                return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"加载市场失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
        
        # 分批执行，减少市场冲击
        try:
            # 对大单进行拆分
            if size > self.config.iceberg_threshold:
                result = self._execute_iceberg_entry(symbol, size, price, stage, exchange)
                # 如果执行成功，记录买入日志
                if result["success"]:
                    # 添加交易所ID信息
                    result["exchange_id"] = exchange_id
                    self._log_entry_order(result)
                return result
            else:
                result = self._execute_single_entry(symbol, size, price, stage, exchange)
                # 如果执行成功，记录买入日志
                if result["success"]:
                    # 添加交易所ID信息
                    result["exchange_id"] = exchange_id
                    self._log_entry_order(result)
                return result
                
        except Exception as e:
            error_msg = f"执行买入订单失败: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
    
    def _execute_single_entry(self, symbol, size, price, stage, exchange):
        """执行单次买入订单
        
        Args:
            symbol: 交易对
            size: 买入数量
            price: 买入价格
            stage: 入场阶段
            exchange: 交易所对象
            
        Returns:
            dict: 订单结果
        """
        self.logger.info(f"执行买入订单: {symbol}, 数量: {size}, 价格: {price}, 阶段: {stage}")
        
        try:
            # 调整买入价格，设置一个合理的溢价，确保能够成交
            market = exchange.market(symbol)
            
            # 获取市场深度
            orderbook = exchange.fetch_order_book(symbol)
            
            # 计算实际价格
            actual_price = self._calculate_buy_price(price, orderbook, market)
            
            # 处理精度问题
            precision = market['precision']['amount']
            adjusted_size = self._adjust_precision(size, precision)
            
            # 计算最小下单额
            min_amount = self._get_min_amount(market)
            
            if adjusted_size * actual_price < min_amount:
                error_msg = f"订单金额 {adjusted_size * actual_price} 小于最小下单额 {min_amount}"
                self.logger.error(error_msg)
                return {"success": False, "error": error_msg}
            
            # 执行买入
            if self.config.dry_run:
                # 模拟买入
                self.logger.info(f"[模拟] 买入 {symbol}: 数量={adjusted_size}, 价格={actual_price}")
                order_id = f"dry_run_{int(time.time())}"
                avg_price = actual_price
            else:
                # 实际买入
                order = exchange.create_limit_buy_order(symbol, adjusted_size, actual_price)
                order_id = order['id']
                
                # 等待订单成交
                filled = self._wait_for_order_fill(order_id, symbol, exchange)
                if not filled:
                    # 如果订单没有完全成交，取消订单
                    exchange.cancel_order(order_id, symbol)
                    # 使用市价单成交剩余部分
                    remaining = exchange.fetch_order(order_id, symbol)['remaining']
                    if remaining > 0:
                        market_order = exchange.create_market_buy_order(symbol, remaining)
                
                # 获取成交均价
                order_info = exchange.fetch_order(order_id, symbol)
                avg_price = order_info['price'] if order_info['price'] else order_info['average']
            
            self.logger.info(f"买入 {symbol} 成功: 订单ID={order_id}, 均价={avg_price}")
            
            result = {
                "success": True,
                "order_id": order_id,
                "symbol": symbol,  # 添加symbol字段
                "size": adjusted_size,
                "avg_price": avg_price,
                "stage": stage,
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            error_msg = f"执行单次买入订单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def _execute_iceberg_entry(self, symbol, size, price, stage, exchange):
        """执行冰山买入订单
        
        Args:
            symbol: 交易对
            size: 买入数量
            price: 买入价格
            stage: 入场阶段
            exchange: 交易所对象
            
        Returns:
            dict: 订单结果
        """
        self.logger.info(f"执行冰山买入订单: {symbol}, 总数量: {size}, 价格: {price}, 阶段: {stage}")
        
        # 分批数量
        batch_count = min(5, math.ceil(size / self.config.iceberg_threshold))
        batch_size = size / batch_count
        
        # 跟踪所有订单
        all_orders = []
        total_filled = 0
        total_cost = 0
        
        try:
            for i in range(batch_count):
                remaining = size - total_filled
                current_batch = min(batch_size, remaining)
                
                self.logger.info(f"冰山买入 {symbol} 第 {i+1}/{batch_count} 批: 数量={current_batch}")
                
                # 执行单个批次
                result = self._execute_single_entry(symbol, current_batch, price, f"{stage}_iceberg_{i+1}", exchange)
                
                if result["success"]:
                    all_orders.append(result)
                    total_filled += result["size"]
                    total_cost += result["size"] * result["avg_price"]
                    
                    # 随机等待，避免被识别为机器人
                    time.sleep(3 + (random.random() * 4))
                else:
                    self.logger.warning(f"冰山买入第 {i+1} 批失败: {result['error']}")
                    break
            
            # 计算平均价格
            avg_price = total_cost / total_filled if total_filled > 0 else price
            
            result = {
                "success": total_filled > 0,
                "symbol": symbol,  # 添加symbol字段
                "size": total_filled,
                "avg_price": avg_price,
                "stage": stage,
                "timestamp": datetime.now().isoformat(),
                "orders": all_orders,
                "is_iceberg": True  # 标记为冰山订单
            }
            
            return result
            
        except Exception as e:
            error_msg = f"执行冰山买入订单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def _log_entry_order(self, order_result):
        """记录买入订单到日志文件
        
        Args:
            order_result: 订单执行结果
        """
        try:
            # 读取现有日志
            existing_logs = []
            if os.path.exists(self.entry_log_file):
                try:
                    with open(self.entry_log_file, 'r', encoding='utf-8') as f:
                        existing_logs = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning(f"无法解析现有日志文件，将创建新的日志文件")
                    existing_logs = []
            
            # 添加新的订单记录
            log_entry = {
                "timestamp": order_result["timestamp"],
                "symbol": order_result["symbol"],
                "exchange_id": order_result.get("exchange_id", self.default_exchange),
                "order_id": order_result.get("order_id", "multiple_orders" if "orders" in order_result else "unknown"),
                "size": order_result["size"],
                "avg_price": order_result["avg_price"],
                "stage": order_result["stage"],
                "is_iceberg": order_result.get("is_iceberg", False),
                "cost": order_result["size"] * order_result["avg_price"]
            }
            
            # 如果是冰山订单，添加子订单信息
            if "orders" in order_result:
                log_entry["sub_orders"] = []
                for sub_order in order_result["orders"]:
                    sub_log = {
                        "order_id": sub_order["order_id"],
                        "size": sub_order["size"],
                        "avg_price": sub_order["avg_price"],
                        "stage": sub_order["stage"],
                        "timestamp": sub_order["timestamp"]
                    }
                    log_entry["sub_orders"].append(sub_log)
            
            existing_logs.append(log_entry)
            
            # 写入日志文件
            with open(self.entry_log_file, 'w', encoding='utf-8') as f:
                json.dump(existing_logs, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"买入订单已记录到日志: {self.entry_log_file}")
            
        except Exception as e:
            self.logger.error(f"记录买入订单到日志失败: {str(e)}", exc_info=True)
    
    def get_entry_orders(self, symbol=None, exchange_id=None, start_time=None, end_time=None):
        """获取买入订单历史记录
        
        Args:
            symbol: 交易对，如果为None则获取所有交易对
            exchange_id: 交易所ID，如果为None则获取所有交易所
            start_time: 开始时间，ISO格式字符串，如果为None则不限制开始时间
            end_time: 结束时间，ISO格式字符串，如果为None则不限制结束时间
            
        Returns:
            list: 买入订单记录列表
        """
        try:
            if not os.path.exists(self.entry_log_file):
                self.logger.warning(f"买入订单日志文件不存在: {self.entry_log_file}")
                return []
            
            # 读取日志文件
            with open(self.entry_log_file, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
            
            # 如果没有筛选条件，返回所有记录
            if symbol is None and exchange_id is None and start_time is None and end_time is None:
                return all_logs
            
            # 根据条件筛选记录
            filtered_logs = []
            for log in all_logs:
                # 筛选交易对
                if symbol is not None and log["symbol"] != symbol:
                    continue
                
                # 筛选交易所
                if exchange_id is not None and log["exchange_id"] != exchange_id:
                    continue
                
                # 筛选时间范围
                log_time = datetime.fromisoformat(log["timestamp"])
                
                if start_time is not None:
                    start = datetime.fromisoformat(start_time)
                    if log_time < start:
                        continue
                
                if end_time is not None:
                    end = datetime.fromisoformat(end_time)
                    if log_time > end:
                        continue
                
                filtered_logs.append(log)
            
            return filtered_logs
            
        except Exception as e:
            self.logger.error(f"获取买入订单历史记录失败: {str(e)}", exc_info=True)
            return []
    
    def execute_exit(self, symbol, size, price, reason, exchange_id=None):
        """执行卖出订单
        
        Args:
            symbol: 交易对
            size: 卖出数量
            price: 卖出价格
            reason: 卖出原因
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单结果
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
        exchange = self.exchanges[exchange_id]
        
        self.logger.info(f"执行卖出订单: {symbol}, 数量: {size}, 价格: {price}, 原因: {reason}")
        
        try:
            # 调整卖出价格，确保能够成交
            market = exchange.market(symbol)
            
            # 获取市场深度
            orderbook = exchange.fetch_order_book(symbol)
            
            # 计算实际价格
            actual_price = self._calculate_sell_price(price, orderbook, market)
            
            # 处理精度问题
            precision = market['precision']['amount']
            adjusted_size = self._adjust_precision(size, precision)
            
            # 执行卖出
            if self.config.dry_run:
                # 模拟卖出
                self.logger.info(f"[模拟] 卖出 {symbol}: 数量={adjusted_size}, 价格={actual_price}")
                order_id = f"dry_run_{int(time.time())}"
                avg_price = actual_price
            else:
                # 卖出策略：先尝试限价单，如果不能迅速成交，则使用市价单
                order = exchange.create_limit_sell_order(symbol, adjusted_size, actual_price)
                order_id = order['id']
                
                # 等待30秒看是否成交
                filled = self._wait_for_order_fill(order_id, symbol, exchange, timeout=30)
                if not filled:
                    # 如果订单没有完全成交，取消订单
                    exchange.cancel_order(order_id, symbol)
                    # 使用市价单成交剩余部分
                    remaining = exchange.fetch_order(order_id, symbol)['remaining']
                    if remaining > 0:
                        market_order = exchange.create_market_sell_order(symbol, remaining)
                
                # 获取成交均价
                order_info = exchange.fetch_order(order_id, symbol)
                avg_price = order_info['price'] if order_info['price'] else order_info['average']
            
            self.logger.info(f"卖出 {symbol} 成功: 订单ID={order_id}, 均价={avg_price}")
            
            result = {
                "success": True,
                "order_id": order_id,
                "symbol": symbol,
                "size": adjusted_size,
                "avg_price": avg_price,
                "reason": reason,
                "timestamp": datetime.now().isoformat()
            }
            
            # 记录卖出日志
            self._log_exit_order(result, exchange_id)
            
            return result
            
        except Exception as e:
            error_msg = f"执行卖出订单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def _log_exit_order(self, order_result, exchange_id):
        """记录卖出订单到日志文件
        
        Args:
            order_result: 订单执行结果
            exchange_id: 交易所ID
        """
        try:
            # 卖出日志文件路径
            exit_log_file = os.path.join(self.log_dir, 'exit_orders.json')
            
            # 读取现有日志
            existing_logs = []
            if os.path.exists(exit_log_file):
                try:
                    with open(exit_log_file, 'r', encoding='utf-8') as f:
                        existing_logs = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning(f"无法解析现有卖出日志文件，将创建新的日志文件")
                    existing_logs = []
            
            # 添加新的订单记录
            log_entry = {
                "timestamp": order_result["timestamp"],
                "symbol": order_result["symbol"],
                "exchange_id": exchange_id,
                "order_id": order_result["order_id"],
                "size": order_result["size"],
                "avg_price": order_result["avg_price"],
                "reason": order_result["reason"],
                "revenue": order_result["size"] * order_result["avg_price"]
            }
            
            # 尝试查找对应的买入记录，计算盈亏
            entry_orders = self.get_entry_orders(symbol=order_result["symbol"], exchange_id=exchange_id)
            if entry_orders:
                # 按时间排序，获取最近的买入记录
                sorted_entries = sorted(entry_orders, key=lambda x: x["timestamp"], reverse=True)
                latest_entry = sorted_entries[0]
                
                # 计算盈亏
                entry_price = latest_entry["avg_price"]
                exit_price = order_result["avg_price"]
                profit_percentage = (exit_price - entry_price) / entry_price * 100
                
                log_entry["entry_order_id"] = latest_entry["order_id"]
                log_entry["entry_price"] = entry_price
                log_entry["profit_percentage"] = profit_percentage
                log_entry["profit_amount"] = (exit_price - entry_price) * order_result["size"]
            
            existing_logs.append(log_entry)
            
            # 写入日志文件
            with open(exit_log_file, 'w', encoding='utf-8') as f:
                json.dump(existing_logs, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"卖出订单已记录到日志: {exit_log_file}")
            
        except Exception as e:
            self.logger.error(f"记录卖出订单到日志失败: {str(e)}", exc_info=True)
    
    def get_exit_orders(self, symbol=None, exchange_id=None, start_time=None, end_time=None):
        """获取卖出订单历史记录
        
        Args:
            symbol: 交易对，如果为None则获取所有交易对
            exchange_id: 交易所ID，如果为None则获取所有交易所
            start_time: 开始时间，ISO格式字符串，如果为None则不限制开始时间
            end_time: 结束时间，ISO格式字符串，如果为None则不限制结束时间
            
        Returns:
            list: 卖出订单记录列表
        """
        try:
            exit_log_file = os.path.join(self.log_dir, 'exit_orders.json')
            
            if not os.path.exists(exit_log_file):
                self.logger.warning(f"卖出订单日志文件不存在: {exit_log_file}")
                return []
            
            # 读取日志文件
            with open(exit_log_file, 'r', encoding='utf-8') as f:
                all_logs = json.load(f)
            
            # 如果没有筛选条件，返回所有记录
            if symbol is None and exchange_id is None and start_time is None and end_time is None:
                return all_logs
            
            # 根据条件筛选记录
            filtered_logs = []
            for log in all_logs:
                # 筛选交易对
                if symbol is not None and log["symbol"] != symbol:
                    continue
                
                # 筛选交易所
                if exchange_id is not None and log["exchange_id"] != exchange_id:
                    continue
                
                # 筛选时间范围
                log_time = datetime.fromisoformat(log["timestamp"])
                
                if start_time is not None:
                    start = datetime.fromisoformat(start_time)
                    if log_time < start:
                        continue
                
                if end_time is not None:
                    end = datetime.fromisoformat(end_time)
                    if log_time > end:
                        continue
                
                filtered_logs.append(log)
            
            return filtered_logs
            
        except Exception as e:
            self.logger.error(f"获取卖出订单历史记录失败: {str(e)}", exc_info=True)
            return []
    
    def get_trading_history(self, symbol=None, exchange_id=None, start_time=None, end_time=None):
        """获取交易历史（包括买入和卖出记录）
        
        Args:
            symbol: 交易对，如果为None则获取所有交易对
            exchange_id: 交易所ID，如果为None则获取所有交易所
            start_time: 开始时间，ISO格式字符串，如果为None则不限制开始时间
            end_time: 结束时间，ISO格式字符串，如果为None则不限制结束时间
            
        Returns:
            dict: 包含买入和卖出记录的字典
        """
        try:
            # 获取买入记录
            entry_orders = self.get_entry_orders(symbol, exchange_id, start_time, end_time)
            
            # 获取卖出记录
            exit_orders = self.get_exit_orders(symbol, exchange_id, start_time, end_time)
            
            # 计算交易统计数据
            stats = self._calculate_trading_stats(entry_orders, exit_orders)
            
            return {
                "entry_orders": entry_orders,
                "exit_orders": exit_orders,
                "stats": stats
            }
            
        except Exception as e:
            self.logger.error(f"获取交易历史失败: {str(e)}", exc_info=True)
            return {"entry_orders": [], "exit_orders": [], "stats": {}}
    
    def _calculate_trading_stats(self, entry_orders, exit_orders):
        """计算交易统计数据
        
        Args:
            entry_orders: 买入订单列表
            exit_orders: 卖出订单列表
            
        Returns:
            dict: 交易统计数据
        """
        stats = {
            "total_entries": len(entry_orders),
            "total_exits": len(exit_orders),
            "total_profit": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0,
            "avg_profit_percentage": 0,
            "max_profit_percentage": 0,
            "max_loss_percentage": 0,
            "total_volume": 0,
            "active_positions": []
        }
        
        # 计算已实现利润
        profit_percentages = []
        for exit_order in exit_orders:
            if "profit_percentage" in exit_order:
                profit = exit_order["profit_percentage"]
                profit_percentages.append(profit)
                stats["total_profit"] += exit_order.get("profit_amount", 0)
                
                if profit > 0:
                    stats["win_count"] += 1
                else:
                    stats["loss_count"] += 1
                
                stats["max_profit_percentage"] = max(stats["max_profit_percentage"], profit) if profit > 0 else stats["max_profit_percentage"]
                stats["max_loss_percentage"] = min(stats["max_loss_percentage"], profit) if profit < 0 else stats["max_loss_percentage"]
                
                stats["total_volume"] += exit_order["revenue"]
        
        # 计算胜率和平均利润率
        if profit_percentages:
            stats["avg_profit_percentage"] = sum(profit_percentages) / len(profit_percentages)
        
        if stats["win_count"] + stats["loss_count"] > 0:
            stats["win_rate"] = stats["win_count"] / (stats["win_count"] + stats["loss_count"]) * 100
        
        # 计算当前持仓（买入但尚未卖出的订单）
        exited_order_ids = set()
        for exit_order in exit_orders:
            if "entry_order_id" in exit_order:
                exited_order_ids.add(exit_order["entry_order_id"])
        
        active_positions = []
        for entry_order in entry_orders:
            order_id = entry_order.get("order_id", "")
            if order_id and order_id not in exited_order_ids:
                active_positions.append(entry_order)
        
        stats["active_positions"] = active_positions
        stats["active_position_count"] = len(active_positions)
        
        return stats
    
    def set_stop_loss(self, symbol, stop_price, size, exchange_id=None):
        """设置止损单
        
        Args:
            symbol: 交易对
            stop_price: 触发价格
            size: 卖出数量
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单结果
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
        exchange = self.exchanges[exchange_id]
        
        self.logger.info(f"设置止损单: {symbol}, 触发价格: {stop_price}, 数量: {size}")
        
        try:
            # 处理精度问题
            market = exchange.market(symbol)
            precision = market['precision']['amount']
            adjusted_size = self._adjust_precision(size, precision)
            
            # 根据交易所是否支持止损单
            if hasattr(exchange, 'create_stop_loss_order'):
                if self.config.dry_run:
                    # 模拟设置止损单
                    self.logger.info(f"[模拟] 设置止损单 {symbol}: 触发价格={stop_price}, 数量={adjusted_size}")
                    order_id = f"dry_run_sl_{int(time.time())}"
                else:
                    # 设置止损单
                    order = exchange.create_stop_loss_order(symbol, adjusted_size, stop_price)
                    order_id = order['id']
                
                self.logger.info(f"设置止损单 {symbol} 成功: 订单ID={order_id}")
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "stop_price": stop_price,
                    "size": adjusted_size,
                    "type": "stop_loss",
                    "timestamp": datetime.now().isoformat()
                }
            else:
                # 如果交易所不支持止损单，记录日志
                self.logger.warning(f"交易所 {exchange_id} 不支持止损单，将使用软止损")
                
                # 返回成功，但提示使用软止损
                return {
                    "success": False,
                    "error": "交易所不支持止损单，使用软止损代替",
                    "stop_price": stop_price,
                    "size": adjusted_size,
                    "type": "soft_stop_loss",
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            error_msg = f"设置止损单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def update_stop_loss(self, symbol, new_stop_price, size, exchange_id=None):
        """更新止损单
        
        Args:
            symbol: 交易对
            new_stop_price: 新的触发价格
            size: 卖出数量
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单结果
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
        exchange = self.exchanges[exchange_id]
        
        self.logger.info(f"更新止损单: {symbol}, 新触发价格: {new_stop_price}, 数量: {size}")
        
        # 取消旧的止损单，然后设置新的
        # 注意：这里假设我们有一个方法来获取止损单ID，实际实现可能需要修改
        try:
            # 取消旧的止损单
            if hasattr(exchange, 'fetch_open_orders'):
                open_orders = exchange.fetch_open_orders(symbol)
                for order in open_orders:
                    if order['type'] == 'stop' or order['type'] == 'stop_loss':
                        exchange.cancel_order(order['id'], symbol)
                        self.logger.info(f"取消旧止损单: ID={order['id']}")
            
            # 设置新的止损单
            return self.set_stop_loss(symbol, new_stop_price, size, exchange_id)
            
        except Exception as e:
            error_msg = f"更新止损单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def set_conditional_order(self, symbol, size, price, stage, condition, exchange_id=None):
        """设置条件单
        
        Args:
            symbol: 交易对
            size: 买入数量
            price: 买入价格
            stage: 入场阶段
            condition: 条件字典，包含type和price
            exchange_id: 交易所ID，如果为None则使用默认交易所
            
        Returns:
            dict: 订单结果
        """
        if exchange_id is None:
            exchange_id = self.default_exchange
            
        if exchange_id not in self.exchanges:
            error_msg = f"交易所 {exchange_id} 不存在"
            self.logger.error(error_msg)
            return {"success": False, "error": error_msg}
            
        exchange = self.exchanges[exchange_id]
        
        self.logger.info(f"设置条件单: {symbol}, 类型: {condition['type']}, 触发价格: {condition['price']}, 买入价格: {price}, 数量: {size}")
        
        try:
            # 处理精度问题
            market = exchange.market(symbol)
            precision = market['precision']['amount']
            adjusted_size = self._adjust_precision(size, precision)
            
            if self.config.dry_run:
                # 模拟设置条件单
                self.logger.info(f"[模拟] 设置条件单 {symbol}: 触发价格={condition['price']}, 买入价格={price}, 数量={adjusted_size}")
                order_id = f"dry_run_cond_{int(time.time())}"
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "trigger_price": condition['price'],
                    "price": price,
                    "size": adjusted_size,
                    "stage": stage,
                    "timestamp": datetime.now().isoformat()
                }
            
            # 检查交易所是否支持条件单
            if hasattr(exchange, 'create_order') and 'trigger' in dir(exchange):
                # 这里假设交易所支持类似FTX的条件单API
                params = {
                    'triggerPrice': condition['price'],
                    'trigger': 'above' if condition['type'] == 'price_above' else 'below'
                }
                
                order = exchange.create_limit_buy_order(symbol, adjusted_size, price, params)
                order_id = order['id']
                
                self.logger.info(f"设置条件单 {symbol} 成功: 订单ID={order_id}")
                
                return {
                    "success": True,
                    "order_id": order_id,
                    "trigger_price": condition['price'],
                    "price": price,
                    "size": adjusted_size,
                    "stage": stage,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                # 交易所不支持条件单
                self.logger.warning(f"交易所 {exchange_id} 不支持条件单，将使用软条件单")
                
                return {
                    "success": False,
                    "error": "交易所不支持条件单，使用软条件单代替",
                    "trigger_price": condition['price'],
                    "price": price,
                    "size": adjusted_size,
                    "stage": stage,
                    "type": "soft_conditional",
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            error_msg = f"设置条件单失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    def _calculate_buy_price(self, target_price, orderbook, market):
        """计算实际买入价格
        
        Args:
            target_price: 目标价格
            orderbook: 订单簿数据
            market: 市场数据
            
        Returns:
            float: 实际买入价格
        """
        # 获取卖单价格
        asks = orderbook['asks']
        
        # 如果没有卖单，使用目标价格
        if not asks:
            return target_price
        
        # 获取最低卖价
        lowest_ask = asks[0][0]
        
        # 如果目标价格高于最低卖价，使用最低卖价
        if target_price >= lowest_ask:
            return lowest_ask
        
        # 否则，提高目标价格一点点，确保能够成交
        # 这里假设价格精度是market['precision']['price']
        price_precision = market['precision']['price']
        
        # 计算一个tick的大小
        tick_size = 1 / (10 ** price_precision) if isinstance(price_precision, int) else float(price_precision)
        
        # 计算适当的价格（稍高于目标价格）
        actual_price = target_price + tick_size
        
        return actual_price
    
    def _calculate_sell_price(self, target_price, orderbook, market):
        """计算实际卖出价格
        
        Args:
            target_price: 目标价格
            orderbook: 订单簿数据
            market: 市场数据
            
        Returns:
            float: 实际卖出价格
        """
        # 获取买单价格
        bids = orderbook['bids']
        
        # 如果没有买单，使用目标价格
        if not bids:
            return target_price
        
        # 获取最高买价
        highest_bid = bids[0][0]
        
        # 如果目标价格低于最高买价，使用最高买价
        if target_price <= highest_bid:
            return highest_bid
        
        # 否则，降低目标价格一点点，确保能够成交
        # 这里假设价格精度是market['precision']['price']
        price_precision = market['precision']['price']
        
        # 计算一个tick的大小
        tick_size = 1 / (10 ** price_precision) if isinstance(price_precision, int) else float(price_precision)
        
        # 计算适当的价格（稍低于目标价格）
        actual_price = target_price - tick_size
        
        return actual_price
    
    def _adjust_precision(self, amount, precision):
        """调整数量精度
        
        Args:
            amount: 原始数量
            precision: 精度
            
        Returns:
            float: 调整后的数量
        """
        # 如果精度是整数，表示小数位数
        if isinstance(precision, int):
            factor = 10 ** precision
            return math.floor(amount * factor) / factor
        # 如果精度是字符串，表示步长
        else:
            step = float(precision)
            return math.floor(amount / step) * step
    
    def _get_min_amount(self, market):
        """获取最小下单金额
        
        Args:
            market: 市场数据
            
        Returns:
            float: 最小下单金额
        """
        # 有些交易所在market.min_order_amount中提供
        if 'limits' in market and 'cost' in market['limits'] and 'min' in market['limits']['cost']:
            return market['limits']['cost']['min']
        # 否则使用配置的默认值
        return self.config.min_order_amount
    
    def _wait_for_order_fill(self, order_id, symbol, exchange, timeout=60):
        """等待订单成交
        
        Args:
            order_id: 订单ID
            symbol: 交易对
            exchange: 交易所对象
            timeout: 超时时间（秒）
            
        Returns:
            bool: 是否完全成交
        """
        self.logger.info(f"等待订单 {order_id} 成交...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                order = exchange.fetch_order(order_id, symbol)
                
                # 检查订单状态
                if order['status'] == 'closed':
                    self.logger.info(f"订单 {order_id} 已完全成交")
                    return True
                elif order['status'] == 'canceled':
                    self.logger.warning(f"订单 {order_id} 已取消")
                    return False
                
                # 检查部分成交
                if order['filled'] > 0:
                    self.logger.info(f"订单 {order_id} 部分成交: {order['filled']}/{order['amount']}")
                
                # 等待一段时间再查询
                time.sleep(3)
                
            except Exception as e:
                self.logger.error(f"查询订单状态出错: {str(e)}")
                time.sleep(5)
        
        self.logger.warning(f"等待订单 {order_id} 成交超时")
        return False 