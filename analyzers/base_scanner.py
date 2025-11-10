# analyzers/base_scanner.py
"""
BaseScanner - 所有语言扫描器的基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any
import sys
import os

# 添加路径以便导入utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.common import Finding
from utils.language_detector import Language


class BaseScanner(ABC):
    """扫描器基类"""

    def __init__(self, files: List[Dict[str, Any]], language: Language):
        """
        Args:
            files: [{"file": "xxx", "content": "...", ...}, ...]
            language: 目标语言
        """
        self.files = files
        self.language = language
        self.findings: List[Finding] = []

    @abstractmethod
    def scan_builtin(self) -> List[Finding]:
        """内置规则扫描（必须实现）"""
        pass

    @abstractmethod
    def scan_external(self, tool_config: Dict[str, bool] = None) -> List[Finding]:
        """外部工具扫描（必须实现）"""
        pass

    def scan_dynamic(self) -> Dict[str, Any]:
        """动态检测（编译/运行检查，可选）"""
        return {"enabled": False, "results": []}

    def scan(self, enable_external: bool = True,
             enable_dynamic: bool = True,
             tool_config: Dict[str, bool] = None) -> Dict[str, Any]:
        """
        执行完整扫描

        Returns:
            {
                "language": "python",
                "builtin": [Finding, ...],
                "external": [Finding, ...],
                "dynamic": {...},
                "summary": {...}
            }
        """
        result = {
            "language": self.language.value,
            "builtin": [],
            "external": [],
            "dynamic": {},
            "summary": {}
        }

        # 1. 内置规则扫描
        try:
            builtin_findings = self.scan_builtin()
            result["builtin"] = [f.to_dict() for f in builtin_findings]
        except Exception as e:
            result["builtin_error"] = str(e)
            result["builtin"] = []

        # 2. 外部工具扫描
        if enable_external:
            try:
                external_findings = self.scan_external(tool_config)
                result["external"] = [f.to_dict() for f in external_findings]
            except Exception as e:
                result["external_error"] = str(e)
                result["external"] = []

        # 3. 动态检测
        if enable_dynamic:
            try:
                result["dynamic"] = self.scan_dynamic()
            except Exception as e:
                result["dynamic_error"] = str(e)
                result["dynamic"] = {}

        # 4. 汇总统计
        all_findings = result["builtin"] + result["external"]
        result["summary"] = {
            "total": len(all_findings),
            "high": sum(1 for f in all_findings if f.get("severity") == "HIGH"),
            "medium": sum(1 for f in all_findings if f.get("severity") == "MEDIUM"),
            "low": sum(1 for f in all_findings if f.get("severity") == "LOW"),
            "by_file": self._count_by_file(all_findings)
        }

        return result

    def _count_by_file(self, findings: List[Dict]) -> Dict[str, int]:
        """统计每个文件的问题数"""
        counts = {}
        for f in findings:
            file = f.get("file", "unknown")
            counts[file] = counts.get(file, 0) + 1
        return counts