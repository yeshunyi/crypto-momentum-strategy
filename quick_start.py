#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速启动脚本，跳过耗时的初始化步骤
"""
import sys
import logging
import argparse
from momentum_strategy import MomentumStrategy
from utils.logger import setup_logger

def main():
    """主函数"""
    # 设置命令行参数
    parser = argparse.ArgumentParser(description="加密货币涨速交易策略快速启动")
    parser.add_argument('--skip-blacklist', action='store_true', help='跳过黑名单初始化')
    parser.add_argument('--skip-sectors', action='store_true', help='跳过板块排名初始化')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logger("quick_start", log_level)
    
    logger.info("快速启动加密货币涨速交易策略...")
    logger.info(f"跳过黑名单初始化: {args.skip_blacklist}")
    logger.info(f"跳过板块排名初始化: {args.skip_sectors}")
    
    try:
        # 初始化策略
        strategy = MomentumStrategy(args.config)
        
        # 注入快速启动设置
        if args.skip_blacklist:
            strategy.update_blacklist = lambda: strategy.risk_manager.blacklist
            logger.info("已设置跳过黑名单更新")
            
        if args.skip_sectors:
            strategy.update_sector_ranking = lambda: []
            logger.info("已设置跳过板块排名更新")
        
        # 启动策略
        logger.info("开始启动策略...")
        strategy.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出程序")
        sys.exit(0)
    except Exception as e:
        logger.error(f"启动策略时出错: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 