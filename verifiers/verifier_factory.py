# verifiers/verifier_factory.py
"""
VerifierFactory - 验证器工厂类
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.language_detector import Language


class VerifierFactory:
    """验证器工厂类 - 根据语言创建相应的验证器"""

    @staticmethod
    def create_verifier(language: Language):
        """
        根据语言创建验证器

        Args:
            language: Language枚举

        Returns:
            对应语言的验证器实例

        Raises:
            ValueError: 不支持的语言
        """
        if language == Language.PYTHON:
            from verifiers.python_verifier import PythonVerifier
            return PythonVerifier()

        elif language == Language.JAVA:
            from verifiers.java_verifier import JavaVerifier
            return JavaVerifier()

        elif language == Language.C or language == Language.CPP:
            from verifiers.cpp_verifier import CppVerifier
            return CppVerifier()

        else:
            raise ValueError(f"不支持的语言: {language}")

    @staticmethod
    def get_supported_languages():
        """获取支持的语言列表"""
        return [Language.PYTHON, Language.JAVA, Language.C, Language.CPP]


# 便捷函数
def create_verifier(language: Language):
    """创建验证器的便捷函数"""
    return VerifierFactory.create_verifier(language)