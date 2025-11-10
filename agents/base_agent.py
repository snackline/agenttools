# -- coding: utf-8 --
"""
Agent基类 - 定义Agent的基本接口和通用能力
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass, asdict
import json
import time


@dataclass
class AgentMessage:
    """Agent之间的消息格式"""
    from_agent: str
    to_agent: str
    action: str
    data: Dict[str, Any]
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self):
        return asdict(self)


class BaseAgent(ABC):
    """Agent基类"""

    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.history: List[AgentMessage] = []
        self.status = "idle"  # idle, working, completed, error

    @abstractmethod
    def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        感知阶段 - 接收输入并处理
        Args:
            input_data: 输入数据
        Returns:
            处理后的感知结果
        """
        pass

    @abstractmethod
    def decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """
        决策阶段 - 基于感知结果做出决策
        Args:
            perception: 感知结果
        Returns:
            决策方案
        """
        pass

    @abstractmethod
    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行阶段 - 执行决策
        Args:
            decision: 决策方案
        Returns:
            执行结果
        """
        pass

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        完整工作流：感知 → 决策 → 执行
        """
        try:
            self.status = "working"

            # 1. 感知
            perception = self.perceive(input_data)

            # 2. 决策
            decision = self.decide(perception)

            # 3. 执行
            result = self.execute(decision)

            self.status = "completed"
            return {
                "success": True,
                "agents": self.name,
                "result": result,
                "perception": perception,
                "decision": decision
            }
        except Exception as e:
            self.status = "error"
            return {
                "success": False,
                "agents": self.name,
                "error": str(e)
            }

    def send_message(self, to_agent: str, action: str, data: Dict[str, Any]):
        """发送消息给其他Agent"""
        msg = AgentMessage(
            from_agent=self.name,
            to_agent=to_agent,
            action=action,
            data=data
        )
        self.history.append(msg)
        return msg

    def log(self, message: str):
        """记录日志"""
        print(f"[{self.name}] {message}")