#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
性能追踪器模块，用于记录和分析策略表现
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import matplotlib.pyplot as plt

from utils.logger import setup_logger

class PerformanceTracker:
    """性能追踪器类，用于记录和分析策略表现"""
    
    def __init__(self, config):
        """初始化性能追踪器
        
        Args:
            config: 配置对象
        """
        self.config = config
        self.logger = setup_logger("performance_tracker", logging.INFO)
        self.logger.info("初始化性能追踪器...")
        
        # 交易记录
        self.trades = []
        
        # 绩效指标
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.total_fees = 0.0
        self.max_drawdown = 0.0
        
        # 初始化数据存储路径
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        self.trades_file = os.path.join(self.data_dir, "trades.json")
        self.performance_file = os.path.join(self.data_dir, "performance.json")
        
        # 创建数据目录（如果不存在）
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        # 加载历史数据
        self._load_data()
        
        self.logger.info("性能追踪器初始化完成")
    
    def record_trade(self, symbol, action, entry_price, exit_price, size, fees=0):
        """记录交易
        
        Args:
            symbol: 交易对
            action: 交易类型（"entry", "exit", "take_profit", "stop_loss"）
            entry_price: 入场价格
            exit_price: 出场价格
            size: 交易数量
            fees: 手续费
        """
        trade = {
            "symbol": symbol,
            "action": action,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "profit_pct": (exit_price / entry_price - 1) * 100 if action in ["exit", "take_profit", "stop_loss"] else 0,
            "profit_amount": (exit_price - entry_price) * size if action in ["exit", "take_profit", "stop_loss"] else 0,
            "fees": fees,
            "timestamp": datetime.now().isoformat()
        }
        
        self.trades.append(trade)
        
        # 更新统计数据
        if action in ["exit", "take_profit", "stop_loss"]:
            self.total_trades += 1
            if trade["profit_amount"] > 0:
                self.winning_trades += 1
                self.total_profit += trade["profit_amount"]
            else:
                self.losing_trades += 1
                self.total_loss += abs(trade["profit_amount"])
            
            self.total_fees += fees
            
            # 记录交易日志
            profit_sign = "+" if trade["profit_amount"] > 0 else ""
            self.logger.info(f"交易记录 - {symbol} {action}: 利润 {profit_sign}{trade['profit_amount']:.2f}美元 ({profit_sign}{trade['profit_pct']:.2f}%)")
        
        # 保存数据
        self._save_data()
    
    def calculate_metrics(self):
        """计算绩效指标
        
        Returns:
            dict: 绩效指标
        """
        # 计算胜率
        win_rate = self.winning_trades / self.total_trades * 100 if self.total_trades > 0 else 0
        
        # 计算盈亏比
        avg_win = self.total_profit / self.winning_trades if self.winning_trades > 0 else 0
        avg_loss = self.total_loss / self.losing_trades if self.losing_trades > 0 else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        
        # 计算期望值
        expectancy = (win_rate / 100 * avg_win) - ((100 - win_rate) / 100 * avg_loss)
        
        # 计算净利润
        net_profit = self.total_profit - self.total_loss - self.total_fees
        
        # 计算最大回撤
        self._calculate_max_drawdown()
        
        # 汇总指标
        metrics = {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": profit_loss_ratio,
            "expectancy": expectancy,
            "total_profit": self.total_profit,
            "total_loss": self.total_loss,
            "total_fees": self.total_fees,
            "net_profit": net_profit,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown / self.config.account_balance * 100 if self.config.account_balance > 0 else 0,
            "timestamp": datetime.now().isoformat()
        }
        
        return metrics
    
    def _calculate_max_drawdown(self):
        """计算最大回撤"""
        if not self.trades:
            self.max_drawdown = 0
            return
            
        # 按时间排序交易
        sorted_trades = sorted(self.trades, key=lambda x: x["timestamp"])
        
        # 计算每笔交易后的余额变化
        balance = self.config.account_balance
        peak_balance = balance
        drawdown = 0
        
        for trade in sorted_trades:
            if trade["action"] in ["exit", "take_profit", "stop_loss"]:
                # 更新余额
                balance += trade["profit_amount"] - trade["fees"]
                
                # 更新峰值
                if balance > peak_balance:
                    peak_balance = balance
                
                # 计算回撤
                current_drawdown = peak_balance - balance
                if current_drawdown > drawdown:
                    drawdown = current_drawdown
        
        self.max_drawdown = drawdown
    
    def daily_report(self):
        """生成每日报告"""
        self.logger.info("生成每日绩效报告...")
        
        # 计算当日交易
        today = datetime.now().date()
        today_trades = [t for t in self.trades if datetime.fromisoformat(t["timestamp"]).date() == today]
        
        if not today_trades:
            self.logger.info("今日无交易记录")
            return
        
        # 计算当日指标
        today_profit = sum([t["profit_amount"] for t in today_trades if t["action"] in ["exit", "take_profit", "stop_loss"]])
        today_fees = sum([t["fees"] for t in today_trades])
        today_net = today_profit - today_fees
        
        today_wins = len([t for t in today_trades if t["action"] in ["exit", "take_profit", "stop_loss"] and t["profit_amount"] > 0])
        today_losses = len([t for t in today_trades if t["action"] in ["exit", "take_profit", "stop_loss"] and t["profit_amount"] <= 0])
        today_total = today_wins + today_losses
        
        # 打印报告
        self.logger.info(f"===== 每日绩效报告 ({today}) =====")
        self.logger.info(f"总交易次数: {today_total}")
        self.logger.info(f"盈利交易: {today_wins}")
        self.logger.info(f"亏损交易: {today_losses}")
        self.logger.info(f"胜率: {(today_wins / today_total * 100) if today_total > 0 else 0:.2f}%")
        self.logger.info(f"总利润: ${today_profit:.2f}")
        self.logger.info(f"总手续费: ${today_fees:.2f}")
        self.logger.info(f"净利润: ${today_net:.2f}")
        
        # 生成并保存完整报告
        metrics = self.calculate_metrics()
        
        report = {
            "date": today.isoformat(),
            "daily_metrics": {
                "trades": today_total,
                "wins": today_wins,
                "losses": today_losses,
                "win_rate": (today_wins / today_total * 100) if today_total > 0 else 0,
                "profit": today_profit,
                "fees": today_fees,
                "net_profit": today_net
            },
            "overall_metrics": metrics,
            "timestamp": datetime.now().isoformat()
        }
        
        # 保存报告
        report_file = os.path.join(self.data_dir, f"report_{today.isoformat()}.json")
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=4)
            
        self.logger.info(f"每日报告已保存至 {report_file}")
        
        # 生成图表
        try:
            self._generate_charts(today)
        except Exception as e:
            self.logger.error(f"生成图表时出错: {str(e)}")
    
    def _generate_charts(self, date):
        """生成绩效图表
        
        Args:
            date: 报告日期
        """
        # 准备数据
        df = pd.DataFrame(self.trades)
        if df.empty:
            return
            
        # 转换时间戳
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # 过滤只包含出场交易
        exits_df = df[df['action'].isin(['exit', 'take_profit', 'stop_loss'])]
        if exits_df.empty:
            return
            
        # 创建图表目录
        charts_dir = os.path.join(self.data_dir, "charts")
        if not os.path.exists(charts_dir):
            os.makedirs(charts_dir)
            
        # 1. 累计收益图
        plt.figure(figsize=(12, 6))
        exits_df['cumulative_profit'] = exits_df['profit_amount'].cumsum()
        plt.plot(exits_df['timestamp'], exits_df['cumulative_profit'], 'b-')
        plt.title('Cumulative Profit Over Time')
        plt.xlabel('Time')
        plt.ylabel('Profit (USD)')
        plt.grid(True)
        plt.savefig(os.path.join(charts_dir, f"cumulative_profit_{date.isoformat()}.png"))
        plt.close()
        
        # 2. 收益分布图
        plt.figure(figsize=(12, 6))
        exits_df['profit_pct'].hist(bins=20)
        plt.title('Profit Distribution')
        plt.xlabel('Profit %')
        plt.ylabel('Frequency')
        plt.grid(True)
        plt.savefig(os.path.join(charts_dir, f"profit_distribution_{date.isoformat()}.png"))
        plt.close()
        
        # 3. 按交易对的收益分析
        if len(exits_df['symbol'].unique()) > 1:
            plt.figure(figsize=(14, 7))
            symbol_profits = exits_df.groupby('symbol')['profit_amount'].sum().sort_values(ascending=False)
            symbol_profits.plot(kind='bar')
            plt.title('Profit by Symbol')
            plt.xlabel('Symbol')
            plt.ylabel('Profit (USD)')
            plt.grid(True)
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(os.path.join(charts_dir, f"profit_by_symbol_{date.isoformat()}.png"))
            plt.close()
    
    def _load_data(self):
        """加载历史数据"""
        try:
            # 加载交易记录
            if os.path.exists(self.trades_file):
                with open(self.trades_file, 'r') as f:
                    self.trades = json.load(f)
                self.logger.info(f"加载了 {len(self.trades)} 条历史交易记录")
                
            # 加载绩效指标
            if os.path.exists(self.performance_file):
                with open(self.performance_file, 'r') as f:
                    metrics = json.load(f)
                    
                self.total_trades = metrics.get('total_trades', 0)
                self.winning_trades = metrics.get('winning_trades', 0)
                self.losing_trades = metrics.get('losing_trades', 0)
                self.total_profit = metrics.get('total_profit', 0.0)
                self.total_loss = metrics.get('total_loss', 0.0)
                self.total_fees = metrics.get('total_fees', 0.0)
                self.max_drawdown = metrics.get('max_drawdown', 0.0)
                
                self.logger.info("加载历史绩效指标完成")
                
        except Exception as e:
            self.logger.error(f"加载历史数据出错: {str(e)}")
    
    def _save_data(self):
        """保存数据"""
        try:
            # 保存交易记录
            with open(self.trades_file, 'w') as f:
                json.dump(self.trades, f, indent=4)
                
            # 保存绩效指标
            metrics = self.calculate_metrics()
            with open(self.performance_file, 'w') as f:
                json.dump(metrics, f, indent=4)
                
        except Exception as e:
            self.logger.error(f"保存数据出错: {str(e)}")
    
    def get_recent_trades(self, count=10):
        """获取最近的交易记录
        
        Args:
            count: 获取数量
            
        Returns:
            list: 最近的交易记录
        """
        sorted_trades = sorted(self.trades, key=lambda x: x["timestamp"], reverse=True)
        return sorted_trades[:count] 