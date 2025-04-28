#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
加密货币涨速交易策略主模块
"""
import logging
import time
from datetime import datetime
import schedule
import traceback
from collections import defaultdict

from config import Config
from data_provider import MarketDataProvider
from market_analyzer import MarketAnalyzer
from signal_generator import SignalGenerator
from risk_manager import RiskManager
from order_executor import OrderExecutor
from performance_tracker import PerformanceTracker
from utils.logger import setup_logger

class MomentumStrategy:
    """加密货币涨速交易策略主类"""
    
    def __init__(self, config_path="config.yaml"):
        """初始化策略
        
        Args:
            config_path: 配置文件路径
        """
        # 初始化日志
        self.logger = setup_logger("momentum_strategy", logging.INFO)
        self.logger.info("初始化涨速交易策略...")
        
        # 加载配置
        self.config = Config(config_path)
        
        # 初始化各模块
        self.data_provider = MarketDataProvider(self.config)
        self.market_analyzer = MarketAnalyzer(self.config)
        
        # 重要：先设置数据提供器，再初始化其他依赖它的组件
        self.market_analyzer.set_data_provider(self.data_provider)
        
        self.signal_generator = SignalGenerator(self.config, self.market_analyzer)
        self.signal_generator.set_data_provider(self.data_provider)
        
        self.risk_manager = RiskManager(self.config)
        self.risk_manager.set_data_provider(self.data_provider)
        
        self.order_executor = OrderExecutor(self.config)
        self.performance_tracker = PerformanceTracker(self.config)
        
        # 策略状态
        self.is_running = False
        self.positions = {}  # 当前持仓
        
        # 性能统计
        self.performance_stats = defaultdict(lambda: {'count': 0, 'total_time': 0, 'max_time': 0})
        
        self.logger.info("策略初始化完成")
    
    def _track_performance(self, task_name, elapsed_time):
        """记录性能统计
        
        Args:
            task_name: 任务名称
            elapsed_time: 耗时(秒)
        """
        stats = self.performance_stats[task_name]
        stats['count'] += 1
        stats['total_time'] += elapsed_time
        stats['max_time'] = max(stats['max_time'], elapsed_time)
        
        # 如果耗时超过阈值，记录警告
        if elapsed_time > 10:  # 超过10秒的任务记录警告
            self.logger.warning(f"任务 {task_name} 耗时较长: {elapsed_time:.2f}秒")
    
    def print_performance_stats(self):
        """打印性能统计信息"""
        self.logger.info("=== 性能统计报告 ===")
        for task, stats in sorted(self.performance_stats.items(), 
                                  key=lambda x: x[1]['total_time'], 
                                  reverse=True):
            avg_time = stats['total_time'] / stats['count'] if stats['count'] > 0 else 0
            self.logger.info(f"任务: {task} | 执行次数: {stats['count']} | "
                           f"总耗时: {stats['total_time']:.2f}秒 | "
                           f"平均耗时: {avg_time:.2f}秒 | "
                           f"最大耗时: {stats['max_time']:.2f}秒")
        self.logger.info("===================")
    
    def start(self):
        """启动策略"""
        self.logger.info("策略启动...")
        self.is_running = True
        
        # 设置定时任务
        schedule.every(self.config.scan_interval).minutes.do(self.scan_market)
        schedule.every(1).hours.do(self.update_sector_ranking)
        schedule.every(1).days.do(self.update_blacklist)
        schedule.every(1).days.at("00:00").do(self.performance_tracker.daily_report)
        
        # 初始化市场数据
        self.logger.info("初始化市场数据...")
        try:
            self.data_provider.init_data()
            self.logger.info("市场数据初始化完成")
        except Exception as e:
            self.logger.error(f"初始化市场数据出错: {str(e)}", exc_info=True)
            self.logger.warning("使用有限功能继续运行")
        
        # 防错处理：确保数据提供器已初始化后再更新板块和黑名单
        try:
            # 初始化黑名单 (限制条目数量以提高初始化速度)
            self.logger.info("初始化黑名单 (快速模式)...")
            symbols = self.data_provider.get_tradable_symbols()[:20]
            if symbols:
                for symbol in symbols[:5]:  # 只检查前5个，加快启动速度
                    if self.risk_manager._check_blacklist_conditions(symbol):
                        self.risk_manager.blacklist.add(symbol)
                self.logger.info(f"快速黑名单初始化完成，已添加 {len(self.risk_manager.blacklist)} 个币种")
            
            # 初始化板块排名
            self.update_sector_ranking()
        except Exception as e:
            self.logger.error(f"初始化时更新板块和黑名单出错: {str(e)}", exc_info=True)
            self.logger.info("跳过初始化环节，继续启动")
        
        # 主循环
        try:
            self.logger.info("策略开始运行...")
            while self.is_running:
                try:
                    # 设置任务执行超时
                    start_time = time.time()
                    schedule.run_pending()
                    
                    # 检查任务执行是否超时
                    execution_time = time.time() - start_time
                    if execution_time > 30:  # 如果执行时间超过30秒，记录警告
                        self.logger.warning(f"定时任务执行耗时较长: {execution_time:.2f}秒")
                    
                    # 监控持仓
                    self.monitor_positions()
                    time.sleep(10)
                except Exception as e:
                    self.logger.error(f"主循环执行出错: {str(e)}", exc_info=True)
                    # 休息一段时间后继续
                    time.sleep(30)
        except KeyboardInterrupt:
            self.logger.info("接收到中断信号，正在停止策略...")
            self.stop()
        except Exception as e:
            self.logger.error(f"策略运行出错: {str(e)}", exc_info=True)
            self.stop()
    
    def stop(self):
        """停止策略"""
        self.logger.info("停止策略...")
        self.is_running = False
        # 可以在这里添加清理代码，如关闭连接等
        self.logger.info("策略已停止")
    
    def scan_market(self):
        """扫描市场，寻找交易机会"""
        self.logger.info("开始扫描市场...")
        overall_start_time = time.time()
        
        try:
            # 获取市场数据
            start_time = time.time()
            symbols = self.data_provider.get_tradable_symbols()
            end_time = time.time()
            self.logger.info(f"获取到{len(symbols)}个可交易币种 (耗时: {end_time-start_time:.2f}秒)")
            self._track_performance("获取交易币种", end_time-start_time)
            
            # 评估市场环境
            start_time = time.time()
            market_state = self.market_analyzer.assess_market_state()
            end_time = time.time()
            self.logger.info(f"当前市场状态: {market_state} (耗时: {end_time-start_time:.2f}秒)")
            self._track_performance("市场状态评估", end_time-start_time)
            
            # 检查风险水平
            start_time = time.time()
            if not self.risk_manager.check_market_risk():
                end_time = time.time()
                self._track_performance("风险检查", end_time-start_time)
                self.logger.warning("市场风险过高，暂停新开仓")
                return
            end_time = time.time()
            self._track_performance("风险检查", end_time-start_time)
            
            # 生成交易信号
            start_time = time.time()
            signals = self.signal_generator.generate_signals(symbols)
            end_time = time.time()
            self._track_performance("信号生成", end_time-start_time)
            
            if not signals:
                self.logger.info("未发现符合条件的交易信号")
                overall_end_time = time.time()
                self.logger.info(f"市场扫描完成，总耗时: {overall_end_time-overall_start_time:.2f}秒")
                return
                
            self.logger.info(f"发现{len(signals)}个潜在交易信号 (信号生成耗时: {end_time-start_time:.2f}秒)")
            
            # 过滤信号（黑名单、风险控制等）
            start_time = time.time()
            filtered_signals = self.risk_manager.filter_signals(signals)
            end_time = time.time()
            self.logger.info(f"过滤后剩余{len(filtered_signals)}个有效信号 (信号过滤耗时: {end_time-start_time:.2f}秒)")
            self._track_performance("信号过滤", end_time-start_time)
            
            # 排序信号
            start_time = time.time()
            ranked_signals = self.risk_manager.rank_signals(filtered_signals)
            end_time = time.time()
            self._track_performance("信号排序", end_time-start_time)
            
            # 执行交易
            start_time = time.time()
            executed_count = 0
            for signal in ranked_signals[:self.config.max_new_positions]:
                if self.risk_manager.can_open_position(signal):
                    try:
                        self.execute_entry(signal)
                        executed_count += 1
                    except Exception as e:
                        self.logger.error(f"执行信号 {signal['symbol']} 失败: {str(e)}")
                        traceback.print_exc()
            end_time = time.time()
            self.logger.info(f"执行了 {executed_count} 个交易信号 (信号执行耗时: {end_time-start_time:.2f}秒)")
            self._track_performance("信号执行", end_time-start_time)
        
            # 输出性能统计
            overall_end_time = time.time()
            self.logger.info(f"市场扫描完成，总耗时: {overall_end_time-overall_start_time:.2f}秒")
            
            # 每10次扫描输出一次性能统计报告
            if self.performance_stats['市场扫描总次数']['count'] % 10 == 0:
                self.print_performance_stats()
                
            # 更新性能统计
            self._track_performance("市场扫描总次数", overall_end_time-overall_start_time)
        
        except Exception as e:
            self.logger.error(f"扫描市场出错: {str(e)}")
            traceback.print_exc()
            overall_end_time = time.time()
            self.logger.error(f"市场扫描异常终止，总耗时: {overall_end_time-overall_start_time:.2f}秒")
    
    def update_sector_ranking(self):
        """更新板块排名"""
        self.logger.info("更新板块排名...")
        start_time = time.time()
        
        try:
            sectors = self.market_analyzer.rank_sectors()
            end_time = time.time()
            
            self.logger.info(f"板块排名更新完成，前3名: {[s['name'] for s in sectors[:3]]} (耗时: {end_time-start_time:.2f}秒)")
            self._track_performance("更新板块排名", end_time-start_time)
            
            return sectors
        except Exception as e:
            end_time = time.time()
            self.logger.error(f"更新板块排名出错: {str(e)}")
            traceback.print_exc()
            self._track_performance("更新板块排名(失败)", end_time-start_time)
            return []
    
    def update_blacklist(self):
        """更新黑名单"""
        self.logger.info("更新币种黑名单...")
        start_time = time.time()
        
        try:
            # 设置超时处理
            # 调用风险管理器更新黑名单
            blacklist = self.risk_manager.update_blacklist()
            
            # 检查执行时间
            end_time = time.time()
            execution_time = end_time - start_time
            
            if execution_time > 60:  # 如果更新超过60秒，发出警告
                self.logger.warning(f"更新黑名单耗时较长: {execution_time:.2f}秒")
            
            self.logger.info(f"黑名单更新完成，共{len(blacklist)}个币种 (耗时: {execution_time:.2f}秒)")
            self._track_performance("更新黑名单", execution_time)
            
            return blacklist
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            
            self.logger.error(f"更新黑名单出错: {str(e)}")
            traceback.print_exc()
            
            # 防止无限等待，设置超时时间
            if execution_time > 120:  # 如果已经过去了120秒
                self.logger.error("更新黑名单超时，强制返回")
            
            self._track_performance("更新黑名单(失败)", execution_time)
            return self.risk_manager.blacklist
    
    def execute_entry(self, signal):
        """执行入场交易
        
        Args:
            signal: 交易信号
        """
        symbol = signal['symbol']
        self.logger.info(f"执行入场交易: {symbol}")
        
        # 计算仓位大小
        position_size = self.risk_manager.calculate_position_size(signal)
        
        # 第一阶段入场（50%仓位）
        first_entry = position_size * 0.5
        order_result = self.order_executor.execute_entry(
            symbol, 
            first_entry, 
            signal['entry_price'], 
            "first_stage"
        )
        
        if order_result['success']:
            # 记录持仓信息
            self.positions[symbol] = {
                'symbol': symbol,
                'entry_time': datetime.now(),
                'entry_price': order_result['avg_price'],
                'position_size': first_entry,
                'stop_loss': order_result['avg_price'] * 0.98,  # 2%止损
                'target_profit': order_result['avg_price'] * (1 + signal['profit_target']),
                'stage': 1,
                'sector': signal['sector'],
                'orders': [order_result]
            }
            
            # 设置第二阶段入场的条件单
            self.setup_second_stage_entry(symbol, position_size * 0.5, signal)
            
            # 设置止损单
            self.order_executor.set_stop_loss(
                symbol, 
                self.positions[symbol]['stop_loss'],
                first_entry
            )
            
            self.logger.info(f"{symbol} 第一阶段入场完成，均价: {order_result['avg_price']}")
        else:
            self.logger.error(f"{symbol} 入场订单执行失败: {order_result['error']}")
    
    def setup_second_stage_entry(self, symbol, size, signal):
        """设置第二阶段入场
        
        Args:
            symbol: 交易币种
            size: 仓位大小
            signal: 交易信号
        """
        self.logger.info(f"设置 {symbol} 第二阶段入场条件")
        
        # 获取前高位置
        previous_high = self.data_provider.get_previous_high(symbol)
        
        # 设置突破前高的条件单
        condition = {
            'type': 'price_above',
            'price': previous_high,
            'rsi_below': 70  # RSI需小于70
        }
        
        self.order_executor.set_conditional_order(
            symbol, 
            size, 
            previous_high * 1.005,  # 稍高一点的价格，避免刚好触发
            "second_stage",
            condition
        )
        
        self.logger.info(f"{symbol} 第二阶段条件单设置完成，触发价: {previous_high}")
    
    def monitor_positions(self):
        """监控当前持仓"""
        if not self.positions:
            return
            
        for symbol, position in list(self.positions.items()):
            try:
                # 获取当前价格
                current_price = self.data_provider.get_current_price(symbol)
                
                # 检查是否需要移动止损
                if current_price / position['entry_price'] > 1.03:  # 盈利超过3%
                    new_stop_loss = max(position['entry_price'], position['stop_loss'] * 1.01)
                    if new_stop_loss > position['stop_loss']:
                        self.order_executor.update_stop_loss(
                            symbol, 
                            new_stop_loss,
                            position['position_size']
                        )
                        self.positions[symbol]['stop_loss'] = new_stop_loss
                        self.logger.info(f"{symbol} 更新移动止损至: {new_stop_loss}")
                
                # 检查分段止盈
                profit_pct = (current_price / position['entry_price'] - 1) * 100
                target_pct = (position['target_profit'] / position['entry_price'] - 1) * 100
                
                if profit_pct >= target_pct * 0.8 and not position.get('take_profit_1', False):
                    # 第一段止盈 (30%)
                    size_to_sell = position['position_size'] * 0.3
                    self.execute_take_profit(symbol, size_to_sell, current_price)
                    self.positions[symbol]['take_profit_1'] = True
                    self.logger.info(f"{symbol} 执行第一段止盈，比例: 30%，价格: {current_price}")
                
                elif profit_pct >= target_pct and not position.get('take_profit_2', False):
                    # 第二段止盈 (40%)
                    size_to_sell = position['position_size'] * 0.4
                    self.execute_take_profit(symbol, size_to_sell, current_price)
                    self.positions[symbol]['take_profit_2'] = True
                    self.logger.info(f"{symbol} 执行第二段止盈，比例: 40%，价格: {current_price}")
                
                elif profit_pct >= target_pct * 1.2 and not position.get('take_profit_3', False):
                    # 第三段止盈 (30%)
                    size_to_sell = position['position_size'] * 0.3
                    self.execute_take_profit(symbol, size_to_sell, current_price)
                    self.positions[symbol]['take_profit_3'] = True
                    self.logger.info(f"{symbol} 执行第三段止盈，比例: 30%，价格: {current_price}")
                    
                    # 所有止盈完成，清除持仓记录
                    del self.positions[symbol]
                
                # 检查时间止损
                position_duration = datetime.now() - position['entry_time']
                if position_duration.total_seconds() / 3600 > 4:  # 超过4小时
                    if profit_pct < 1:  # 盈利不足1%
                        self.logger.info(f"{symbol} 触发时间止损，持仓时间超过4小时且盈利不足")
                        self.execute_exit(symbol, position['position_size'], current_price)
                        del self.positions[symbol]
            
            except Exception as e:
                self.logger.error(f"监控持仓 {symbol} 出错: {str(e)}", exc_info=True)
    
    def execute_take_profit(self, symbol, size, price):
        """执行止盈
        
        Args:
            symbol: 交易币种
            size: 平仓大小
            price: 平仓价格
        """
        self.logger.info(f"执行止盈: {symbol}，数量: {size}，价格: {price}")
        result = self.order_executor.execute_exit(symbol, size, price, "take_profit")
        
        if result['success']:
            # 更新持仓信息
            self.positions[symbol]['position_size'] -= size
            self.logger.info(f"{symbol} 止盈执行成功，剩余持仓: {self.positions[symbol]['position_size']}")
            
            # 记录绩效
            self.performance_tracker.record_trade(
                symbol, 
                "take_profit", 
                self.positions[symbol]['entry_price'],
                result['avg_price'],
                size
            )
        else:
            self.logger.error(f"{symbol} 止盈订单执行失败: {result['error']}")
    
    def execute_exit(self, symbol, size, price):
        """执行完全退出
        
        Args:
            symbol: 交易币种
            size: 平仓大小
            price: 平仓价格
        """
        self.logger.info(f"执行完全退出: {symbol}，数量: {size}，价格: {price}")
        result = self.order_executor.execute_exit(symbol, size, price, "exit_all")
        
        if result['success']:
            # 记录绩效
            self.performance_tracker.record_trade(
                symbol, 
                "exit", 
                self.positions[symbol]['entry_price'],
                result['avg_price'],
                size
            )
            self.logger.info(f"{symbol} 完全退出执行成功")
        else:
            self.logger.error(f"{symbol} 退出订单执行失败: {result['error']}")

if __name__ == "__main__":
    # 创建并启动策略
    strategy = MomentumStrategy()
    strategy.start() 