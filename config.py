#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置管理模块，负责加载和管理配置
"""
import os
import json
import yaml
import logging
from utils.logger import setup_logger

class Config:
    """配置类，负责加载和管理配置"""
    
    def __init__(self, config_file=None):
        """初始化配置
        
        Args:
            config_file: 配置文件路径，默认会先尝试yaml文件，再尝试json文件
        """
        self.logger = setup_logger("config", logging.INFO)
        self.logger.info("加载配置...")
        
        # 配置文件路径
        if config_file is None:
            # 如果未指定配置文件，先尝试yaml文件，再尝试json文件
            if os.path.exists("config.yaml"):
                self.config_file = "config.yaml"
                self.config_type = "yaml"
            elif os.path.exists("config.yml"):
                self.config_file = "config.yml"
                self.config_type = "yaml"
            elif os.path.exists("config.json"):
                self.config_file = "config.json"
                self.config_type = "json"
            else:
                raise FileNotFoundError("未找到配置文件，请提供config.yaml、config.yml或config.json文件")
        else:
            self.config_file = config_file
            # 根据文件扩展名确定配置类型
            if config_file.endswith(('.yaml', '.yml')):
                self.config_type = "yaml"
            elif config_file.endswith('.json'):
                self.config_type = "json"
            else:
                raise ValueError("不支持的配置文件格式，请使用YAML或JSON格式")
        
        # 加载配置
        self._load_config()
        
        self.logger.info("配置加载完成")
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_file):
                self.logger.error(f"配置文件不存在: {self.config_file}")
                raise FileNotFoundError(f"配置文件不存在: {self.config_file}")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                if self.config_type == "yaml":
                    self.logger.info(f"正在加载YAML配置文件: {self.config_file}")
                    config = yaml.safe_load(f)
                else:
                    self.logger.info(f"正在加载JSON配置文件: {self.config_file}")
                    config = json.load(f)
            
            # 设置基本配置属性
            self.exchanges = config.get("exchanges", [])
            self.default_exchange = config.get("default_exchange", "")
            self.api_keys = config.get("api_keys", {})
            self.test_mode = config.get("test_mode", False)
            self.dry_run = config.get("dry_run", True)
            self.log_dir = config.get("log_dir", "logs")
            self.iceberg_threshold = config.get("iceberg_threshold", 1.0)
            self.min_order_amount = config.get("min_order_amount", 10.0)
            
            # 读取策略配置
            self.strategies = config.get("strategies", {})
            
            self.logger.info(f"从 {self.config_file} 加载了配置")
            
        except Exception as e:
            self.logger.error(f"加载配置失败: {str(e)}")
            raise
    
    def get_strategy_config(self, strategy_name):
        """获取指定策略的配置
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            dict: 策略配置
        """
        if strategy_name not in self.strategies:
            self.logger.warning(f"策略 {strategy_name} 的配置不存在")
            return {}
        
        return self.strategies[strategy_name]
    
    def is_strategy_enabled(self, strategy_name):
        """检查策略是否启用
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            bool: 策略是否启用
        """
        strategy_config = self.get_strategy_config(strategy_name)
        return strategy_config.get("enabled", False)
    
    def get_strategy_parameters(self, strategy_name):
        """获取策略参数
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            dict: 策略参数
        """
        strategy_config = self.get_strategy_config(strategy_name)
        return strategy_config.get("parameters", {})
    
    def get_strategy_symbols(self, strategy_name):
        """获取策略交易对
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            list: 策略交易对列表
        """
        strategy_config = self.get_strategy_config(strategy_name)
        return strategy_config.get("symbols", [])
    
    def save_config(self):
        """保存配置到文件"""
        try:
            config = {
                "exchanges": self.exchanges,
                "default_exchange": self.default_exchange,
                "api_keys": self.api_keys,
                "test_mode": self.test_mode,
                "dry_run": self.dry_run,
                "log_dir": self.log_dir,
                "iceberg_threshold": self.iceberg_threshold,
                "min_order_amount": self.min_order_amount,
                "strategies": self.strategies
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                if self.config_type == "yaml":
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                else:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"配置已保存到 {self.config_file}")
            
        except Exception as e:
            self.logger.error(f"保存配置失败: {str(e)}")
            raise
    
    def update_strategy_parameter(self, strategy_name, parameter_name, value):
        """更新策略参数
        
        Args:
            strategy_name: 策略名称
            parameter_name: 参数名称
            value: 参数值
        """
        if strategy_name not in self.strategies:
            self.strategies[strategy_name] = {"enabled": True, "parameters": {}}
        
        if "parameters" not in self.strategies[strategy_name]:
            self.strategies[strategy_name]["parameters"] = {}
        
        self.strategies[strategy_name]["parameters"][parameter_name] = value
        
        self.logger.info(f"更新策略 {strategy_name} 参数 {parameter_name}={value}")
        
        # 保存配置
        self.save_config() 