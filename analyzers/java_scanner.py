# analyzers/java_scanner.py
"""
JavaScanner - Java代码扫描器
支持：PMD, Checkstyle, SpotBugs
"""
import os
import re
import json
import shutil
import tempfile
import subprocess
from typing import Dict, List, Any
from xml.etree import ElementTree as ET

from .base_scanner import BaseScanner, Finding, Language


class JavaScanner(BaseScanner):
    """Java专用扫描器"""

    def __init__(self, files: List[Dict[str, Any]]):
        super().__init__(files, Language.JAVA)

    def scan_builtin(self) -> List[Finding]:
        """内置规则扫描：检测常见Java问题"""
        findings = []

        for f in self.files:
            filename = f.get("file", "")
            content = f.get("content", "")
            if not content:
                continue

            lines = content.split('\n')

            # 规则1: 空catch块
            for i, line in enumerate(lines, 1):
                if re.search(r'catch\s*\([^)]+\)\s*\{\s*\}', line):
                    findings.append(Finding(
                        file=filename,
                        line=i,
                        column=0,
                        severity="MEDIUM",
                        rule_id="JAVA001",
                        message="空catch块：异常被吞掉，应至少记录日志",
                        snippet=line.strip()[:100],
                        language=self.language.value,
                        fix_suggestion="添加日志记录或重新抛出异常"
                    ))

            # 规则2: System.out.println 在生产代码中
            if "Test" not in filename and "test" not in filename.lower():
                for i, line in enumerate(lines, 1):
                    if "System.out.print" in line and not line.strip().startswith("//"):
                        findings.append(Finding(
                            file=filename,
                            line=i,
                            column=0,
                            severity="LOW",
                            rule_id="JAVA002",
                            message="使用System.out.print输出，应使用日志框架",
                            snippet=line.strip()[:100],
                            language=self.language.value,
                            fix_suggestion="替换为logger.info()或logger.debug()"
                        ))

            # 规则3: == 比较字符串
            for i, line in enumerate(lines, 1):
                if re.search(r'\w+\s*==\s*"[^"]*"', line) or re.search(r'"[^"]*"\s*==\s*\w+', line):
                    if not line.strip().startswith("//"):
                        findings.append(Finding(
                            file=filename,
                            line=i,
                            column=0,
                            severity="HIGH",
                            rule_id="JAVA003",
                            message="使用==比较字符串，应使用.equals()方法",
                            snippet=line.strip()[:100],
                            language=self.language.value,
                            fix_suggestion="替换为str1.equals(str2)"
                        ))

            # 规则4: 未关闭的资源
            for i, line in enumerate(lines, 1):
                if re.search(
                        r'new\s+(FileReader|FileWriter|BufferedReader|BufferedWriter|FileInputStream|FileOutputStream|Scanner)\s*\(',
                        line):
                    context = '\n'.join(lines[max(0, i - 5):min(len(lines), i + 10)])
                    if 'try' not in context or 'finally' not in context:
                        findings.append(Finding(
                            file=filename,
                            line=i,
                            column=0,
                            severity="HIGH",
                            rule_id="JAVA004",
                            message="资源可能未正确关闭，建议使用try-with-resources",
                            snippet=line.strip()[:100],
                            language=self.language.value,
                            fix_suggestion="使用 try(Resource r = new Resource()) { ... }"
                        ))

            # 规则5: 空指针风险
            for i, line in enumerate(lines, 1):
                if re.search(r'\.\w+\s*\(', line) and 'if' not in line and 'null' in line:
                    findings.append(Finding(
                        file=filename,
                        line=i,
                        column=0,
                        severity="MEDIUM",
                        rule_id="JAVA005",
                        message="潜在的空指针异常风险",
                        snippet=line.strip()[:100],
                        language=self.language.value,
                        fix_suggestion="添加null检查或使用Optional"
                    ))

        return findings

    def scan_external(self, tool_config: Dict[str, bool] = None) -> List[Finding]:
        """外部工具扫描：PMD, Checkstyle"""
        if tool_config is None:
            tool_config = {
                "pmd": True,
                "checkstyle": False,  # 默认禁用（需要配置文件）
                "spotbugs": False,  # 默认禁用（需要编译）
            }

        findings = []

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="java_scan_")
        try:
            # 写入文件
            for f in self.files:
                filename = f.get("file", "").replace("/", os.sep)
                content = f.get("content", "")

                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'w', encoding='utf-8') as fp:
                    fp.write(content)

            # PMD
            if tool_config.get("pmd", True):
                findings.extend(self._run_pmd(tmp_dir))

            # Checkstyle
            if tool_config.get("checkstyle", False):
                findings.extend(self._run_checkstyle(tmp_dir))

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return findings

    def _run_pmd(self, tmp_dir: str) -> List[Finding]:
        """运行PMD静态分析"""
        findings = []

        try:
            # 检查PMD是否安装
            result = subprocess.run(
                ["pmd", "--version"],
                capture_output=True,
                timeout=5,
                text=True
            )
            if result.returncode != 0:
                print("⚠️ PMD未安装或不可用")
                return findings
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("⚠️ PMD未找到")
            return findings

        try:
            cmd = [
                "pmd", "check",
                "-d", tmp_dir,
                "-f", "json",
                "-R", "category/java/bestpractices.xml,category/java/errorprone.xml,category/java/codestyle.xml",
                "--no-cache",
                "--no-progress",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            # PMD返回非0也可能有结果
            if result.stdout:
                try:
                    data = json.loads(result.stdout)

                    for file_data in data.get("files", []):
                        filename = os.path.basename(file_data.get("filename", ""))

                        for violation in file_data.get("violations", []):
                            severity = self._map_pmd_severity(violation.get("priority", 3))
                            findings.append(Finding(
                                file=filename,
                                line=violation.get("beginline", 0),
                                column=violation.get("begincolumn", 0),
                                severity=severity,
                                rule_id=f"PMD_{violation.get('rule', 'UNKNOWN')}",
                                message=violation.get("description", ""),
                                language=self.language.value,
                                tool="pmd"
                            ))
                except json.JSONDecodeError as e:
                    print(f"⚠️ PMD输出解析失败: {e}")

        except subprocess.TimeoutExpired:
            print("⚠️ PMD执行超时")
        except Exception as e:
            print(f"⚠️ PMD执行失败: {e}")

        return findings

    def _run_checkstyle(self, tmp_dir: str) -> List[Finding]:
        """运行Checkstyle代码风格检查"""
        findings = []
        # 实现类似PMD的逻辑
        # 由于需要checkstyle.jar和配置文件，这里暂时跳过
        return findings

    def _map_pmd_severity(self, priority: int) -> str:
        """映射PMD优先级到标准严重程度"""
        if priority == 1:
            return "HIGH"
        elif priority == 2:
            return "HIGH"
        elif priority == 3:
            return "MEDIUM"
        elif priority == 4:
            return "LOW"
        else:
            return "LOW"

    def scan_dynamic(self) -> Dict[str, Any]:
        """动态检测：编译检查"""
        result = {
            "enabled": True,
            "compile_errors": [],
            "compile_success": False
        }

        tmp_dir = tempfile.mkdtemp(prefix="java_compile_")
        try:
            # 写入文件
            java_files = []
            for f in self.files:
                filename = f.get("file", "").replace("/", os.sep)
                content = f.get("content", "")

                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

                with open(filepath, 'w', encoding='utf-8') as fp:
                    fp.write(content)
                java_files.append(filepath)

            # 尝试编译
            compile_cmd = ["javac", "-encoding", "UTF-8", "-d", tmp_dir] + java_files
            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if compile_result.returncode == 0:
                result["compile_success"] = True
            else:
                result["compile_success"] = False
                # 解析编译错误
                stderr = compile_result.stderr
                for line in stderr.split('\n'):
                    if '.java:' in line:
                        result["compile_errors"].append(line.strip())

        except subprocess.TimeoutExpired:
            result["compile_errors"].append("编译超时")
        except Exception as e:
            result["compile_errors"].append(f"编译失败: {str(e)}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result