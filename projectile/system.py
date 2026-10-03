"""
投掷物系统 - 核心模块（带bug版本）

已知问题：
- 抛物线无空气阻力初速写死
- 碰撞只查地面不查墙和天花板
- 弹性系数写死无摩擦力
- 爆炸后不销毁计时器从扔出时算
- 引信不支持碰撞触发
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math
import time


@dataclass
class Config:
    """配置项"""
    pass


class ProjectileSystem:
    """投掷物系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state = {}
        self._history = []

    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []
