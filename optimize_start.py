#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
优化启动脚本，用于诊断和解决策略的性能问题
"""
import sys
import logging
import argparse
import time
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os
import schedule

from momentum_strategy import MomentumStrategy
from utils.logger import setup_logger

def diagnose_performance_issues(strategy, duration=300):
    """诊断性能问题
    
    Args:
        strategy: 策略实例
        duration: 诊断持续时间（秒）
    """
    logger = setup_logger("optimizer", logging.INFO)
    logger.info(f"开始性能诊断，持续 {duration} 秒...")
    
    # 创建结果目录
    os.makedirs("diagnostics", exist_ok=True)
    
    # 记录初始时间
    start_time = time.time()
    
    # 诊断计数
    scan_count = 0
    
    try:
        # 强制立即执行一次扫描
        strategy.scan_market()
        scan_count += 1
        
        # 继续执行直到达到指定时间
        while time.time() - start_time < duration:
            # 每30秒执行一次扫描
            time.sleep(10)
            if time.time() - start_time > scan_count * 30:
                strategy.scan_market()
                scan_count += 1
    except KeyboardInterrupt:
        logger.info("诊断被用户中断")
    except Exception as e:
        logger.error(f"诊断过程发生错误: {str(e)}")
    
    # 收集并分析结果
    logger.info(f"诊断完成，共执行了 {scan_count} 次市场扫描")
    
    # 打印性能统计
    strategy.print_performance_stats()
    
    # 保存性能数据
    performance_data = []
    for task, stats in strategy.performance_stats.items():
        avg_time = stats['total_time'] / stats['count'] if stats['count'] > 0 else 0
        performance_data.append({
            'task': task, 
            'count': stats['count'],
            'total_time': stats['total_time'],
            'avg_time': avg_time,
            'max_time': stats['max_time']
        })
    
    # 转换为DataFrame并排序
    df = pd.DataFrame(performance_data)
    if not df.empty:
        df = df.sort_values('total_time', ascending=False)
        
        # 保存为CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = f"diagnostics/performance_{timestamp}.csv"
        df.to_csv(csv_file, index=False)
        logger.info(f"性能数据已保存到 {csv_file}")
        
        # 生成图表
        plt.figure(figsize=(12, 8))
        plt.barh(df['task'][:10], df['avg_time'][:10], color='skyblue')
        plt.xlabel('平均执行时间 (秒)')
        plt.ylabel('任务')
        plt.title('任务平均执行时间 Top 10')
        plt.tight_layout()
        chart_file = f"diagnostics/performance_chart_{timestamp}.png"
        plt.savefig(chart_file)
        logger.info(f"性能图表已保存到 {chart_file}")
    
    # 提供优化建议
    logger.info("\n=== 优化建议 ===")
    if not df.empty:
        top_tasks = df.sort_values('total_time', ascending=False)['task'].tolist()[:3]
        
        for task in top_tasks:
            if task == "获取交易币种":
                logger.info("1. 币种获取优化: 减少支持的交易对数量，在config.yaml中配置过滤条件")
            elif task == "信号生成":
                logger.info("2. 信号生成优化: 增加信号预过滤条件，减少需要详细分析的币种数量")
            elif task == "更新黑名单":
                logger.info("3. 黑名单优化: 减少黑名单更新频率，使用quick_start.py --skip-blacklist参数")
            elif task == "更新板块排名":
                logger.info("4. 板块排名优化: 减少板块更新频率，使用quick_start.py --skip-sectors参数")
            elif "ATR" in task or "RSI" in task:
                logger.info("5. 指标计算优化: 调整技术指标计算的缓存设置，减少重复计算")
    
    logger.info("6. 总体建议: 使用较大的扫描间隔，减少API请求频率，提高缓存效率")
    logger.info("7. 调整配置: 设置更长的data_refresh_interval以增加缓存有效期")
    logger.info("==================")

def main():
    """主函数"""
    # 设置命令行参数
    parser = argparse.ArgumentParser(description="加密货币涨速交易策略性能优化")
    parser.add_argument('--diagnose', action='store_true', help='执行性能诊断')
    parser.add_argument('--duration', type=int, default=300, help='诊断持续时间(秒)')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logger("optimizer", log_level)
    
    logger.info("加密货币涨速交易策略性能优化工具")
    
    try:
        # 初始化策略
        strategy = MomentumStrategy(args.config)
        
        if args.diagnose:
            # 执行性能诊断
            diagnose_performance_issues(strategy, args.duration)
        else:
            # 正常启动策略（但使用了性能优化设置）
            logger.info("使用性能优化设置启动策略...")
            # 设置更低的扫描频率
            schedule.every(10).minutes.do(strategy.scan_market)  # 每10分钟扫描一次
            schedule.every(2).hours.do(strategy.update_sector_ranking)  # 每2小时更新一次板块
            schedule.every(12).hours.do(strategy.update_blacklist)  # 每12小时更新一次黑名单
            schedule.every(1).days.at("00:00").do(strategy.performance_tracker.daily_report)
            
            # 启动策略
            strategy.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出程序")
        sys.exit(0)
    except Exception as e:
        logger.error(f"运行过程中出错: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 