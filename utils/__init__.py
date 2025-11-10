# utils/__init__.py
"""
Utils模块 - 通用工具类
"""

from .language_detector import Language, LanguageDetector
from .common import *

__all__ = [
    'Language',
    'LanguageDetector',
]