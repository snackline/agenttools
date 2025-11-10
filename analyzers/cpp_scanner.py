# analyzers/cpp_scanner.py
"""
CppScanner - C/C++代码扫描器
支持：cppcheck, clang-tidy
"""
import os
import re
import json
import shutil
import tempfile
import subprocess
from typing import Dict, List, Any

from .base_scanner import BaseScanner, Finding, Language


class CppScanner(BaseScanner):
    """C/C++专用扫描器"""

    def __init__(self, files: List[Dict[str, Any]], language: Language = Language.CPP):
        super().__init__(files, language)

    def scan_builtin(self) -> List[Finding]:
        """内置规则扫描：检测常见C/C++问题"""
        findings = []

        for f in self.files:
            filename = f.get("file", "")
            content = f.get("content", "")
            if not content:
                continue

            lines = content.split('\n')

            # 规则1: 使用gets()（危险函数）
            for i, line in enumerate(lines, 1):
                if re.search(r'\bgets\s*\(', line):
                    findings.append(Finding(
                        file=filename,
                        line=i,
                        column=0,
                        severity="HIGH",
                        rule_id="CPP001",
                        message="使用危险函数gets()，存在缓冲区溢出风险",
                        snippet=line.strip()[:100],
                        language=self.language.value,
                        fix_suggestion="替换为fgets()或std::getline()"
                    ))

            # 规则2: 使用strcpy()（不安全）
            for i, line in enumerate(lines, 1):
                if re.search(r'\bstrcpy\s*\(', line):
                    findings.append(Finding(
                        file=filename,
                        line=i,
                        column=0,
                        severity="MEDIUM",
                        rule_id="CPP002",
                        message="使用strcpy()可能导致缓冲区溢出",
                        snippet=line.strip()[:100],
                        language=self.language.value,
                        fix_suggestion="替换为strncpy()或std::string"
                    ))

            # 规则3: malloc/free不匹配
            malloc_count = len(re.findall(r'\bmalloc\s*\(', content))
            free_count = len(re.findall(r'\bfree\s*\(', content))
            if malloc_count != free_count:
                findings.append(Finding(
                    file=filename,
                    line=1,
                    column=0,
                    severity="HIGH",
                    rule_id="CPP003",
                    message=f"malloc/free不匹配：malloc={malloc_count}, free={free_count}，可能存在内存泄漏",
                    snippet="",
                    language=self.language.value,
                    fix_suggestion="确保每个malloc都有对应的free"
                ))

            # 规则4: 使用NULL解引用
            for i, line in enumerate(lines, 1):
                if re.search(r'\*\s*\w+\s*=', line) and 'if' not in line:
                    findings.append(Finding(
                        file=filename,
                        line=i,
                        column=0,
                        severity="MEDIUM",
                        rule_id="CPP004",
                        message="潜在的空指针解引用风险",
                        snippet=line.strip()[:100],
                        language=self.language.value,
                        fix_suggestion="添加NULL检查"
                    ))

            # 规则5: 数组越界（简单检测）
            for i, line in enumerate(lines, 1):
                match = re.search(r'(\w+)\[(\d+)\]', line)
                if match:
                    # 检查前面是否有数组声明
                    array_name = match.group(1)
                    index = int(match.group(2))

                    for prev_line in lines[:i]:
                        size_match = re.search(rf'{array_name}\[(\d+)\]', prev_line)
                        if size_match:
                            size = int(size_match.group(1))
                            if index >= size:
                                findings.append(Finding(
                                    file=filename,
                                    line=i,
                                    column=0,
                                    severity="HIGH",
                                    rule_id="CPP005",
                                    message=f"数组越界：数组大小={size}，访问索引={index}",
                                    snippet=line.strip()[:100],
                                    language=self.language.value,
                                    fix_suggestion="检查数组索引范围"
                                ))
                            break

        return findings

    def scan_external(self, tool_config: Dict[str, bool] = None) -> List[Finding]:
        """外部工具扫描：cppcheck, clang-tidy"""
        if tool_config is None:
            tool_config = {
                "cppcheck": True,
                "clang-tidy": False,  # 需要compile_commands.json
            }

        findings = []

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="cpp_scan_")
        try:
            # 写入文件
            cpp_files = []
            for f in self.files:
                filename = f.get("file", "").replace("/", os.sep)
                content = f.get("content", "")

                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'w', encoding='utf-8') as fp:
                    fp.write(content)
                cpp_files.append(filepath)

            # cppcheck
            if tool_config.get("cppcheck", True):
                findings.extend(self._run_cppcheck(cpp_files))

            # clang-tidy
            if tool_config.get("clang-tidy", False):
                findings.extend(self._run_clang_tidy(cpp_files))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return findings

    def _run_cppcheck(self, file_paths: List[str]) -> List[Finding]:
        """运行cppcheck静态分析"""
        findings = []

        try:
            # 检查cppcheck是否安装
            result = subprocess.run(
                ["cppcheck", "--version"],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode != 0:
                print("⚠️ cppcheck未安装")
                return findings
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("⚠️ cppcheck未找到")
            return findings

        try:
            cmd = [
                      "cppcheck",
                      "--enable=all",
                      "--inconclusive",
                      "--xml",
                      "--xml-version=2",
                  ] + file_paths

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            # cppcheck输出在stderr
            if result.stderr:
                try:
                    from xml.etree import ElementTree as ET
                    root = ET.fromstring(result.stderr)

                    for error in root.findall(".//error"):
                        for location in error.findall("location"):
                            severity = self._map_cppcheck_severity(error.get("severity", "style"))
                            findings.append(Finding(
                                file=os.path.basename(location.get("file", "")),
                                line=int(location.get("line", 0)),
                                column=int(location.get("column", 0)),
                                severity=severity,
                                rule_id=f"CPPCHECK_{error.get('id', 'UNKNOWN')}",
                                message=error.get("msg", ""),
                                language=self.language.value,
                                tool="cppcheck"
                            ))
                except ET.ParseError as e:
                    print(f"⚠️ cppcheck输出解析失败: {e}")

        except subprocess.TimeoutExpired:
            print("⚠️ cppcheck执行超时")
        except Exception as e:
            print(f"⚠️ cppcheck执行失败: {e}")

        return findings

    def _run_clang_tidy(self, file_paths: List[str]) -> List[Finding]:
        """运行clang-tidy静态分析"""
        findings = []
        # 实现类似cppcheck的逻辑
        # 需要compile_commands.json，这里暂时跳过
        return findings

    def _map_cppcheck_severity(self, severity: str) -> str:
        """映射cppcheck严重程度到标准严重程度"""
        severity_map = {
            "error": "HIGH",
            "warning": "MEDIUM",
            "style": "LOW",
            "performance": "MEDIUM",
            "portability": "LOW",
            "information": "LOW",
        }
        return severity_map.get(severity, "MEDIUM")

    def scan_dynamic(self) -> Dict[str, Any]:
        """动态检测：编译检查"""
        result = {
            "enabled": True,
            "compile_errors": [],
            "compile_success": False
        }

        tmp_dir = tempfile.mkdtemp(prefix="cpp_compile_")
        try:
            # 写入文件
            cpp_files = []
            for f in self.files:
                filename = f.get("file", "").replace("/", os.sep)
                content = f.get("content", "")

                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'w', encoding='utf-8') as fp:
                    fp.write(content)

                # 只编译.c/.cpp文件
                if filename.endswith(('.c', '.cpp', '.cc', '.cxx')):
                    cpp_files.append(filepath)

            if not cpp_files:
                result["compile_errors"].append("没有可编译的源文件")
                return result

            # 选择编译器
            compiler = "g++" if self.language == Language.CPP else "gcc"

            # 尝试编译
            compile_cmd = [
                              compiler,
                              "-std=c++17" if self.language == Language.CPP else "-std=c11",
                              "-Wall",
                              "-Wextra",
                              "-c",  # 只编译不链接
                          ] + cpp_files

            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=tmp_dir
            )

            if compile_result.returncode == 0:
                result["compile_success"] = True
            else:
                result["compile_success"] = False
                # 解析编译错误
                stderr = compile_result.stderr
                for line in stderr.split('\n'):
                    if 'error:' in line or 'warning:' in line:
                        result["compile_errors"].append(line.strip())

        except subprocess.TimeoutExpired:
            result["compile_errors"].append("编译超时")
        except Exception as e:
            result["compile_errors"].append(f"编译失败: {str(e)}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result