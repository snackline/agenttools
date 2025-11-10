# utils/common.py
"""
通用数据结构定义
"""
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional


@dataclass
class Finding:
    """通用缺陷数据结构（跨语言）"""
    file: str
    line: int
    column: int
    severity: str  # HIGH, MEDIUM, LOW
    rule_id: str
    message: str
    snippet: str = ""
    language: str = ""
    tool: str = "builtin"
    fix_suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class FixResult:
    """修复结果数据结构（跨语言）"""
    file: str
    language: str
    original_content: str
    fixed_content: str
    fixed_count: int
    method: str  # "rule" 或 "llm"
    success: bool
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class VerificationResult:
    """验证结果数据结构（跨语言）"""
    file: str
    language: str
    compile_success: bool
    test_success: bool
    remaining_issues: List[Dict]
    new_issues: List[Dict]
    fix_rate: float
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)