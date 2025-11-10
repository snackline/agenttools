# fixers/fixer_factory.py
"""
FixerFactory - 修复器工厂类
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.language_detector import Language


class FixerFactory:
    """修复器工厂类 - 根据语言创建相应的修复器"""

    @staticmethod
    def create_fixer(language: Language, llm_client=None):
        """
        根据语言创建修复器

        Args:
            language: Language枚举
            llm_client: LLM客户端（可选）

        Returns:
            对应语言的修复器实例

        Raises:
            ValueError: 不支持的语言
        """
        if language == Language.PYTHON:
            from fixers.python_fixer import PythonFixer
            return PythonFixer(llm_client)

        elif language == Language.JAVA:
            from fixers.java_fixer import JavaFixer
            return JavaFixer(llm_client)

        elif language == Language.C or language == Language.CPP:
            from fixers.cpp_fixer import CppFixer
            return CppFixer(llm_client)

        else:
            raise ValueError(f"不支持的语言: {language}")

    @staticmethod
    def get_supported_languages():
        """获取支持的语言列表"""
        return [Language.PYTHON, Language.JAVA, Language.C, Language.CPP]


# 便捷函数
def create_fixer(language: Language, llm_client=None):
    """创建修复器的便捷函数"""
    return FixerFactory.create_fixer(language, llm_client)