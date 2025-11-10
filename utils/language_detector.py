# utils/language_detector.py
"""
LanguageDetector - 自动检测代码语言
"""
import os
import re
from typing import Dict, List, Optional
from enum import Enum


class Language(Enum):
    """支持的编程语言"""
    PYTHON = "python"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, lang_str: str):
        """从字符串转换"""
        lang_map = {
            "python": cls.PYTHON,
            "py": cls.PYTHON,
            "java": cls.JAVA,
            "c": cls.C,
            "cpp": cls.CPP,
            "c++": cls.CPP,
        }
        return lang_map.get(lang_str.lower(), cls.UNKNOWN)


class LanguageDetector:
    """语言检测器"""

    # 文件扩展名映射
    EXTENSION_MAP = {
        '.py': Language.PYTHON,
        '.pyw': Language.PYTHON,
        '.pyi': Language.PYTHON,
        '.java': Language.JAVA,
        '.c': Language.C,
        '.h': Language.C,
        '.cpp': Language.CPP,
        '.cc': Language.CPP,
        '.cxx': Language.CPP,
        '.c++': Language.CPP,
        '.hpp': Language.CPP,
        '.hh': Language.CPP,
        '.hxx': Language.CPP,
    }

    # 语言特征关键词
    LANGUAGE_PATTERNS = {
        Language.PYTHON: [
            r'^\s*def\s+\w+\s*\(',
            r'^\s*class\s+\w+\s*[\(:]',
            r'^\s*import\s+\w+',
            r'^\s*from\s+\w+\s+import',
            r'@\w+\s*$',  # decorators
            r'^\s*if\s+__name__\s*==\s*["\']__main__["\']',
        ],
        Language.JAVA: [
            r'^\s*public\s+(class|interface|enum)',
            r'^\s*private\s+',
            r'^\s*protected\s+',
            r'^\s*import\s+java\.',
            r'^\s*package\s+[\w.]+;',
            r'System\.(out|err)\.',
            r'^\s*@Override',
        ],
        Language.C: [
            r'#include\s*<\w+\.h>',
            r'^\s*int\s+main\s*\(',
            r'\bprintf\s*\(',
            r'\bscanf\s*\(',
            r'\bmalloc\s*\(',
            r'^\s*typedef\s+struct',
        ],
        Language.CPP: [
            r'#include\s*<(iostream|string|vector|map)>',
            r'^\s*namespace\s+\w+',
            r'^\s*class\s+\w+\s*[{:]',
            r'\bstd::',
            r'^\s*using\s+namespace\s+std;',
            r'\bcout\s*<<',
            r'\bcin\s*>>',
            r'^\s*template\s*<',
        ],
    }

    # 工具链配置
    LANGUAGE_TOOLS = {
        Language.PYTHON: {
            "name": "Python",
            "extensions": [".py", ".pyw"],
            "comment": "#",
            "builtin_tools": ["ast", "compile"],
            "external_tools": ["ruff", "pylint", "mypy", "bandit"],
            "compiler": "python3",
            "compile_cmd": ["python3", "-m", "py_compile"],
            "run_cmd": ["python3"],
        },
        Language.JAVA: {
            "name": "Java",
            "extensions": [".java"],
            "comment": "//",
            "builtin_tools": [],
            "external_tools": ["pmd", "checkstyle", "spotbugs"],
            "compiler": "javac",
            "compile_cmd": ["javac", "-encoding", "UTF-8"],
            "run_cmd": ["java"],
        },
        Language.C: {
            "name": "C",
            "extensions": [".c", ".h"],
            "comment": "//",
            "builtin_tools": [],
            "external_tools": ["cppcheck", "clang-tidy", "cpplint"],
            "compiler": "gcc",
            "compile_cmd": ["gcc", "-Wall", "-Wextra"],
            "run_cmd": ["./a.out"],
        },
        Language.CPP: {
            "name": "C++",
            "extensions": [".cpp", ".cc", ".cxx", ".hpp", ".hh"],
            "comment": "//",
            "builtin_tools": [],
            "external_tools": ["cppcheck", "clang-tidy", "cpplint"],
            "compiler": "g++",
            "compile_cmd": ["g++", "-std=c++17", "-Wall", "-Wextra"],
            "run_cmd": ["./a.out"],
        },
    }

    @classmethod
    def detect_by_filename(cls, filename: str) -> Language:
        """根据文件名检测语言"""
        _, ext = os.path.splitext(filename.lower())
        return cls.EXTENSION_MAP.get(ext, Language.UNKNOWN)

    @classmethod
    def detect_by_content(cls, content: str, max_lines: int = 100) -> Language:
        """根据文件内容检测语言"""
        if not content:
            return Language.UNKNOWN

        lines = content.split('\n')[:max_lines]
        sample = '\n'.join(lines)

        scores = {lang: 0 for lang in Language if lang != Language.UNKNOWN}

        for lang, patterns in cls.LANGUAGE_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, sample, re.MULTILINE)
                scores[lang] += len(matches)

        if not any(scores.values()):
            return Language.UNKNOWN

        detected_lang = max(scores, key=scores.get)
        return detected_lang if scores[detected_lang] > 0 else Language.UNKNOWN

    @classmethod
    def detect(cls, filename: str, content: str = None) -> Language:
        """综合检测：优先使用扩展名，必要时分析内容"""
        lang = cls.detect_by_filename(filename)

        # 如果扩展名无法确定，且提供了内容，则分析内容
        if lang == Language.UNKNOWN and content:
            lang = cls.detect_by_content(content)

        # C/C++ 歧义处理：.h 文件需要内容判断
        if lang == Language.C and content and filename.lower().endswith('.h'):
            if any(re.search(p, content, re.MULTILINE)
                   for p in cls.LANGUAGE_PATTERNS[Language.CPP]):
                lang = Language.CPP

        return lang

    @classmethod
    def classify_files(cls, files: List[Dict]) -> Dict[Language, List[Dict]]:
        """将文件列表按语言分类"""
        classified = {lang: [] for lang in Language}

        for f in files:
            filename = f.get("file") or f.get("path") or f.get("name", "")
            content = f.get("content", "")

            lang = cls.detect(filename, content)
            classified[lang].append(f)

        return classified

    @classmethod
    def get_language_info(cls, lang: Language) -> Dict:
        """获取语言的工具链信息"""
        return cls.LANGUAGE_TOOLS.get(lang, {
            "name": "Unknown",
            "tools": [],
            "compiler": None,
        })

    @classmethod
    def get_supported_languages(cls) -> List[Language]:
        """获取支持的语言列表（不包括UNKNOWN）"""
        return [lang for lang in Language if lang != Language.UNKNOWN]