# analyzers/scanner_factory.py
"""
ScannerFactory - 根据语言创建对应的扫描器
"""
import sys
import os
from typing import List, Dict, Any

# 添加路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.language_detector import Language
from .base_scanner import BaseScanner
from .defect_scanner import DefectScanner  # 原有的Python扫描器
from .java_scanner import JavaScanner
from .cpp_scanner import CppScanner


class DefectScannerAdapter:
    """
    适配器：将 DefectScanner 的字典返回转换为列表返回
    确保与多Agent系统的接口一致
    """

    def __init__(self, files: List[Dict[str, Any]]):
        self.scanner = DefectScanner(files)
        self.files = files

    def scan(self) -> List[Dict[str, Any]]:
        """
        执行内置规则扫描，返回列表格式的缺陷

        Returns:
            缺陷列表 [{"file": "...", "line": ..., ...}, ...]
        """
        result = self.scanner.scan(
            enable_external=False,  # 内置扫描不使用外部工具
            enable_dynamic=False  # 内置扫描不使用动态检测
        )

        # 提取 static_builtin 列表
        static_builtin = result.get("static_builtin", [])

        # 确保返回的是列表
        if isinstance(static_builtin, list):
            return static_builtin

        return []

    def scan_with_external_tools(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        使用外部工具扫描

        Args:
            files: 文件列表

        Returns:
            外部工具发现的缺陷列表
        """
        result = self.scanner.scan(
            enable_external=True,
            enable_dynamic=False
        )

        # 合并外部工具结果
        external_defects = []
        external_data = result.get("external", {})

        # 遍历所有外部工具的结果
        for tool_name, tool_data in external_data.items():
            if isinstance(tool_data, dict):
                # 提取 findings 列表
                findings = tool_data.get("findings", [])
                if isinstance(findings, list):
                    external_defects.extend(findings)
            elif isinstance(tool_data, list):
                # 如果直接是列表，直接添加
                external_defects.extend(tool_data)

        return external_defects

    def check_compilation(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行编译检查

        Args:
            files: 文件列表

        Returns:
            编译检查结果 {"compile_success": bool, "errors": [...]}
        """
        result = self.scanner.scan(
            enable_external=False,
            enable_dynamic=True
        )

        dynamic = result.get("dynamic", {})
        compile_errors = dynamic.get("py_compile", [])

        return {
            "compile_success": len(compile_errors) == 0,
            "errors": compile_errors,
            "details": dynamic
        }


class ScannerFactory:
    """扫描器工厂"""

    @staticmethod
    def create_scanner(files: list, language: Language):
        """
        根据语言创建对应的扫描器

        Args:
            files: 文件列表
            language: 目标语言

        Returns:
            对应语言的扫描器实例
        """
        if language == Language.PYTHON:
            # ✅ 使用适配器包装 DefectScanner
            return DefectScannerAdapter(files)

        elif language == Language.JAVA:
            return JavaScanner(files)

        elif language == Language.CPP or language == Language.C:
            return CppScanner(files, language)

        else:
            raise ValueError(f"不支持的语言: {language}")

    @staticmethod
    def get_supported_languages():
        """获取支持的语言列表"""
        return [Language.PYTHON, Language.JAVA, Language.C, Language.CPP]