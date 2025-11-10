# fixers/__init__.py
"""
Fixers模块 - 多语言代码修复器
"""

from .base_fixer import BaseFixer, FixResult
from .fixer_factory import FixerFactory, create_fixer

# 延迟导入具体的修复器，避免循环导入
__all__ = [
    'BaseFixer',
    'FixResult',
    'FixerFactory',
    'create_fixer',
]


def get_fixer(language, llm_client=None):
    """
    获取指定语言的修复器（便捷函数）

    Args:
        language: 语言类型（Language枚举或字符串）
        llm_client: LLM客户端（可选）

    Returns:
        对应语言的修复器实例
    """
    from utils.language_detector import Language

    # 如果传入的是字符串，转换为Language枚举
    if isinstance(language, str):
        language = Language.from_string(language)

    return create_fixer(language, llm_client)


def get_supported_languages():
    """获取所有支持的语言"""
    return FixerFactory.get_supported_languages()