# -- coding: utf-8 --
"""
DefectScanner - 增强版缺陷检测器
支持：AST 安全规则、Python2 兼容、未定义名、可变默认参数、函数参数错误等
外部工具：ruff（旧版兼容）、mypy（文本模式）、bandit
"""

from __future__ import annotations
import os
import re
import sys
import ast
import json
import shutil
import subprocess
import tempfile
import py_compile
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Tuple, Optional, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

DEBUG_SCANNER = os.environ.get("SCANNER_DEBUG", "0") == "1"
CODE_FILE_EXTS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.cs', '.php'}


@dataclass
class Finding:
    file: str
    line: int
    col: int
    severity: str  # HIGH / MEDIUM / LOW
    rule_id: str
    message: str
    snippet: str = ""


def _basename(p: str) -> str:
    return (p or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


class _ComprehensiveAstVisitor(ast.NodeVisitor):
    """增强的 AST 访问器：安全 + 质量 + 未定义名 + 参数检查"""

    def __init__(self, code: str, filename: str):
        self.code = code
        self.filename = filename
        self.findings: List[Finding] = []
        self._lines = code.splitlines()

        # 追踪定义的名称
        self.defined_names: Set[str] = set()
        self.imported_names: Set[str] = set()

        # 扩展内置名称列表（修复误报）
        self.builtin_names = set([
            # 内置类型
            'int', 'str', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
            'bytes', 'bytearray', 'complex', 'frozenset', 'object', 'type',
            # 内置函数
            'print', 'len', 'range', 'open', 'input', 'enumerate', 'zip',
            'map', 'filter', 'sum', 'min', 'max', 'abs', 'all', 'any',
            'sorted', 'reversed', 'iter', 'next', 'isinstance', 'issubclass',
            'hasattr', 'getattr', 'setattr', 'delattr', 'dir', 'vars', 'locals', 'globals',
            'callable', 'id', 'hash', 'hex', 'oct', 'bin', 'chr', 'ord',
            'eval', 'exec', 'compile', '__import__',
            # 内置异常
            'Exception', 'BaseException', 'ValueError', 'TypeError', 'KeyError',
            'AttributeError', 'IndexError', 'NameError', 'RuntimeError',
            'ImportError', 'ModuleNotFoundError', 'FileNotFoundError',
            'OSError', 'IOError', 'ZeroDivisionError', 'StopIteration',
            # 内置常量
            'True', 'False', 'None', 'Ellipsis', 'NotImplemented',
            # 特殊名称
            '__name__', '__file__', '__doc__', '__package__', '__loader__',
            '__spec__', '__annotations__', '__builtins__', '__cached__',
            # typing 常用类型
            'List', 'Dict', 'Set', 'Tuple', 'Optional', 'Union', 'Any',
        ])

        # 当前作用域（用于追踪 self 等）
        self.current_scope: List[str] = []
        self.in_class = False
        self.in_function = False

    def _add(self, node: ast.AST, severity: str, rule_id: str, message: str):
        line = getattr(node, "lineno", 1) or 1
        col = getattr(node, "col_offset", 0) or 0
        snippet = self._lines[line - 1][:200] if 1 <= line <= len(self._lines) else ""
        self.findings.append(Finding(self.filename, line, col, severity, rule_id, message, snippet))

    # ========== 导入追踪 ==========
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imported_names.add(name)
            self.defined_names.add(name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            if alias.name == '*':
                self._add(node, "LOW", "PY050", "使用 from X import * 可能导致命名冲突。")
            else:
                name = alias.asname if alias.asname else alias.name
                self.imported_names.add(name)
                self.defined_names.add(name)
        self.generic_visit(node)

    # ========== 定义追踪 ==========
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.defined_names.add(node.name)

        # 进入函数作用域，添加参数名
        old_in_function = self.in_function
        self.in_function = True

        # 添加所有参数到定义名称
        for arg in node.args.args:
            self.defined_names.add(arg.arg)
        for arg in (node.args.posonlyargs or []):
            self.defined_names.add(arg.arg)
        for arg in (node.args.kwonlyargs or []):
            self.defined_names.add(arg.arg)
        if node.args.vararg:
            self.defined_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.defined_names.add(node.args.kwarg.arg)

        # 检测可变默认参数
        for default in node.args.defaults or []:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(node, "HIGH", "AST001",
                          f"函数 {node.name} 的默认参数为可变对象，所有调用将共享同一对象。")
            elif isinstance(default, ast.Call):
                self._add(node, "MEDIUM", "AST003",
                          f"函数 {node.name} 的默认参数为函数调用，该值在函数定义时就会固定。")

        self.generic_visit(node)
        self.in_function = old_in_function

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.defined_names.add(node.name)

        # 添加参数名
        for arg in node.args.args:
            self.defined_names.add(arg.arg)

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.defined_names.add(node.name)

        # 进入类作用域
        old_in_class = self.in_class
        self.in_class = True

        # 添加 self 和 cls 到定义名称
        self.defined_names.add('self')
        self.defined_names.add('cls')

        # dataclass 可变默认值检查
        has_dataclass = any(
            (isinstance(dec, ast.Name) and dec.id == "dataclass") or
            (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "dataclass")
            for dec in node.decorator_list
        )

        if has_dataclass:
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.value, (ast.List, ast.Dict, ast.Set)):
                    target_name = item.target.id if isinstance(item.target, ast.Name) else "字段"
                    self._add(item, "HIGH", "AST001",
                              f"dataclass 字段 {target_name} 的默认值为可变对象，所有实例将共享。")
                elif isinstance(item, ast.AnnAssign) and isinstance(item.value, ast.Call):
                    target_name = item.target.id if isinstance(item.target, ast.Name) else "字段"
                    if isinstance(item.value.func, ast.Attribute):
                        self._add(item, "MEDIUM", "AST003",
                                  f"dataclass 字段 {target_name} 的默认值为函数调用，该值在类定义时固定。")

        self.generic_visit(node)
        self.in_class = old_in_class

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.defined_names.add(target.id)

                # 检测覆盖内建名
                if target.id in self.builtin_names and target.id not in ['list', 'dict', 'set']:
                    self._add(node, "MEDIUM", "PY051",
                              f"覆盖内建名称 '{target.id}'，可能导致意外行为。")

                # 硬编码凭据
                pat = re.compile(r"(password|passwd|secret|api[_-]?key|token)", re.I)
                if (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                        and pat.search(target.id) and len(node.value.value) >= 6):
                    self._add(node, "HIGH", "PY012", f"疑似硬编码凭据变量：{target.id}。")
            elif isinstance(target, ast.Tuple):
                # 处理解包赋值
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        self.defined_names.add(elt.id)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        """处理类型注解赋值"""
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        """处理 for 循环变量"""
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            for elt in node.target.elts:
                if isinstance(elt, ast.Name):
                    self.defined_names.add(elt.id)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension):
        """处理列表推导式等变量"""
        if isinstance(node.target, ast.Name):
            self.defined_names.add(node.target.id)
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp):
        """处理列表推导式"""
        for gen in node.generators:
            if isinstance(gen.target, ast.Name):
                self.defined_names.add(gen.target.id)
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp):
        """处理字典推导式"""
        for gen in node.generators:
            if isinstance(gen.target, ast.Name):
                self.defined_names.add(gen.target.id)
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp):
        """处理集合推导式"""
        for gen in node.generators:
            if isinstance(gen.target, ast.Name):
                self.defined_names.add(gen.target.id)
        self.generic_visit(node)

    def visit_With(self, node: ast.With):
        """处理 with 语句变量"""
        for item in node.items:
            if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                self.defined_names.add(item.optional_vars.id)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        """处理异常处理变量"""
        if node.name:
            self.defined_names.add(node.name)

        if node.type is None:
            self._add(node, "LOW", "PY010", "使用裸 except，建议捕获具体异常类型。")
        elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
            self._add(node, "LOW", "PY011", f"过于宽泛的异常捕获：{node.type.id}。")

        self.generic_visit(node)

    # ========== 使用追踪（未定义名检测）==========
    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load):
            name = node.id

            # 🔥 新增：宽松模式 - 只检测明显的未定义名称
            # 排除条件更宽泛，减少误报
            is_likely_undefined = (
                    name not in self.defined_names and
                    name not in self.imported_names and
                    name not in self.builtin_names and
                    # 🔥 排除单字母变量（循环变量、Lambda参数等）
                    len(name) > 1 and
                    # 🔥 排除下划线开头（私有变量、魔法方法等）
                    not name.startswith('_') and
                    # 🔥 排除常见的第三方库名称（容错）
                    name not in {'pd', 'np', 'plt', 'tf', 'torch', 'cv2', 'requests', 'json', 'time', 'datetime', 'os',
                                 'sys', 're', 'math', 'random'}
            )

            if is_likely_undefined:
                # 🔥 降低严重程度：HIGH → MEDIUM
                self._add(node, "MEDIUM", "PY100", f"疑似使用了未定义的名称 '{name}'（可能为动态导入或第三方库）。")
        elif isinstance(node.ctx, ast.Store):
            self.defined_names.add(node.id)

        self.generic_visit(node)

    # ========== is 比较检测 ==========
    def visit_Compare(self, node: ast.Compare):
        for op in node.ops:
            if isinstance(op, (ast.Is, ast.IsNot)):
                self._add(node, "MEDIUM", "AST002",
                          "疑似使用 'is' 进行值比较，建议使用 '==' （is 仅用于 None/True/False）。")
        self.generic_visit(node)

    # ========== 安全检查 ==========
    def visit_Call(self, node: ast.Call):
        # eval/exec
        if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            self._add(node, "HIGH", "PY001", f"使用 {node.func.id} 可能导致代码执行漏洞。")

        # os.system / os.popen
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id in ("subprocess", "os") and node.func.attr in ("system", "popen"):
                self._add(node, "HIGH", "PY002",
                          f"调用 {node.func.value.id}.{node.func.attr} 存在命令注入风险。")

        # subprocess shell=True
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen", "call", "check_output"):
            for kw in node.keywords or []:
                if kw.arg == "shell" and getattr(kw.value, "value", None) is True:
                    self._add(node, "HIGH", "PY003", "subprocess.*(shell=True) 可能导致命令注入。")

        # yaml.load
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "yaml" and node.func.attr == "load"):
            safe = any(kw.arg == "Loader" and "SafeLoader" in getattr(kw.value, "id", "")
                       for kw in node.keywords or [])
            if not safe:
                self._add(node, "HIGH", "PY005", "yaml.load 未使用 SafeLoader，存在反序列化风险。")

        # pickle
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pickle" and node.func.attr in ("load", "loads")):
            self._add(node, "HIGH", "PY006", "使用 pickle 反序列化存在安全风险。")

        # SQL 拼接
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany"):
            if node.args and isinstance(node.args[0], (ast.BinOp, ast.JoinedStr)):
                self._add(node, "HIGH", "PY008", "疑似 SQL 注入（拼接式 SQL），请使用参数化查询。")

        self.generic_visit(node)


class DefectScanner:
    def __init__(self, files: List[Dict[str, Any]]):
        # 过滤代码文件
        filtered = []
        for f in files:
            name = f.get("name") or f.get("path") or ""
            ext = os.path.splitext(name)[1].lower()
            if ext in CODE_FILE_EXTS:
                filtered.append(f)
        self.files = filtered

        # 构建文件映射
        self.file_map: Dict[str, str] = {}
        for f in self.files:
            name = f.get("path") or f.get("name") or ""
            basename = _basename(name)
            self.file_map[basename] = f.get("content", "")

    def scan(self, enable_external: bool = True, enable_dynamic: bool = True,
             dynamic_timeout: int = 60) -> Dict[str, Any]:
        result: Dict[str, Any] = {"static_builtin": [], "external": {}, "dynamic": {}}

        # 1. 内置静态分析
        builtin_findings = self.run_static_builtin()

        # 2. 外部工具
        tmp_dir, written_paths = self.write_to_temp()
        try:
            external_res = {}
            external_findings: List[Finding] = []
            if enable_external and written_paths:
                external_res = self.run_external_tools(tmp_dir, written_paths, dynamic_timeout)
                external_findings = self._external_to_findings(external_res)

            # 合并所有静态检查结果
            merged = builtin_findings + external_findings
            result["static_builtin"] = [asdict(f) for f in merged]
            result["external"] = external_res

            # 3. 动态检查
            if enable_dynamic:
                result["dynamic"] = self.run_dynamic_light(tmp_dir, dynamic_timeout)
            else:
                result["dynamic"] = {"enabled": False}

            return result
        finally:
            if os.path.isdir(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ========== 内置静态分析 ==========
    def run_static_builtin(self) -> List[Finding]:
        findings: List[Finding] = []
        for f in self.files:
            path = f.get("path", f.get("name", ""))
            basename = _basename(path)
            content = f.get("content", "")

            if not path.endswith('.py'):
                continue

            try:
                tree = ast.parse(content, filename=basename)
                v = _ComprehensiveAstVisitor(content, basename)
                v.visit(tree)
                findings.extend(v.findings)

                # 文本级检查
                findings.extend(self._scan_text_level(basename, content))

            except SyntaxError as e:
                line = getattr(e, "lineno", 1) or 1
                lines = content.splitlines()
                snippet = lines[line - 1][:200] if 1 <= line <= len(lines) else ""
                findings.append(Finding(basename, line, 0, "HIGH", "PY000",
                                        f"语法错误：{e.msg}", snippet))
                # 即使语法错误也做文本检查
                findings.extend(self._scan_text_level(basename, content))
        return findings

    def _scan_text_level(self, basename: str, content: str) -> List[Finding]:
        """文本级别检查：Python2 兼容、错误的文件操作模式等"""
        res: List[Finding] = []
        lines = content.splitlines()

        def add(line_no: int, rule: str, msg: str, sev: str = "MEDIUM"):
            snippet = lines[line_no - 1][:200] if 1 <= line_no <= len(lines) else ""
            res.append(Finding(basename, line_no, 0, sev, rule, msg, snippet))

        # 🔥 选项1：完全禁用文本级检查（最激进）
        # return res  # 直接返回空列表

        # 🔥 选项2：只保留高危检查，移除低危检查
        # Python 2 兼容性 - 保留
        for m in re.finditer(r"\bxrange\s*\(", content):
            ln = content[:m.start()].count("\n") + 1
            add(ln, "PY201", "检测到 Python 2 的 xrange()，在 Python 3 中应改为 range()。", "MEDIUM")  # 🔥 降级为 MEDIUM

        # 🔥 移除 raw_input 检查（不常见）
        # for m in re.finditer(r"\braw_input\s*\(", content):
        #     ln = content[:m.start()].count("\n") + 1
        #     add(ln, "PY203", "检测到 Python 2 的 raw_input()...", "MEDIUM")

        # 文件打开模式错误 - 保留（实用）
        for m in re.finditer(r'open\([^)]*,\s*["\']w["\']\s*\).*?\.read\(', content):
            ln = content[:m.start()].count("\n") + 1
            add(ln, "PY200", "以写入模式 'w' 打开文件后尝试读取，应使用 'r'。", "HIGH")

        for m in re.finditer(r'open\([^)]*,\s*["\']r["\']\s*\)[^.]*\.(write|dump)', content):
            ln = content[:m.start()].count("\n") + 1
            add(ln, "PY201", "以只读模式 'r' 打开文件后尝试写入，应使用 'w' 或 'a'。", "HIGH")

        # 🔥 移除 max() 检查（误报率高）
        # for m in re.finditer(r'max\([^)]*\bfor\b[^)]*\)', content):
        #     ln = content[:m.start()].count("\n") + 1
        #     add(ln, "PY202", "在生成器上使用 max()...", "MEDIUM")

        # 🔥 移除 list.remove() 检查（误报率极高）
        # for m in re.finditer(r'\.remove\(\s*\w+\s*\)', content):
        #     ln = content[:m.start()].count("\n") + 1
        #     add(ln, "PY203", "list.remove() 要求参数为列表中的元素...", "LOW")

        return res

    # ========== 写入临时目录 ==========
    def write_to_temp(self) -> Tuple[str, List[str]]:
        tmp_dir = tempfile.mkdtemp(prefix="scan_")
        written_paths: List[str] = []
        for f in self.files:
            name = f.get("path") or f.get("name") or ""
            base = _basename(name)
            if not base:
                continue
            dst = os.path.join(tmp_dir, base)
            try:
                with open(dst, "w", encoding="utf-8", newline="\n") as fp:
                    fp.write(f.get("content", ""))
                written_paths.append(dst)
            except Exception:
                pass
        return tmp_dir, written_paths

    # ========== 外部工具 ==========
    def run_external_tools(self, tmp_dir: str, file_paths: List[str],
                           timeout_sec: int = 90) -> Dict[str, Any]:
        external: Dict[str, Any] = {}

        # ruff（兼容旧版，使用 --output-format）
        try:
            res = self._run_ruff(tmp_dir, file_paths, timeout_sec)
            external["ruff"] = res
        except Exception as e:
            external["ruff"] = {"error": str(e), "stderr": ""}

        # pylint
        try:
            res = self._run_pylint(tmp_dir, file_paths, timeout_sec)
            external["pylint"] = res
        except Exception as e:
            external["pylint"] = {"error": str(e), "stderr": ""}

        # mypy（文本模式，兼容性最好）
        try:
            res = self._run_mypy(tmp_dir, file_paths, timeout_sec)
            external["mypy"] = res
        except Exception as e:
            external["mypy"] = {"error": str(e), "stderr": ""}

        # bandit
        try:
            res = self._run_bandit(tmp_dir, timeout_sec)
            external["bandit"] = res
        except Exception as e:
            external["bandit"] = {"skipped": True, "reason": str(e), "stderr": ""}

        # semgrep 默认跳过
        external["semgrep"] = {"count": 0, "findings": []}
        return external

    def run_external_tools_java(self, tmp_dir: str, file_paths: List[str],
                                timeout_sec: int = 90) -> Dict[str, Any]:
        """Java 专用外部工具检测"""
        external: Dict[str, Any] = {}

        # 1. Checkstyle（代码风格）
        try:
            cmd = [
                "java", "-jar", "checkstyle.jar",
                "-c", "/google_checks.xml",  # 使用 Google 或 Sun 风格
                "-f", "xml",
                tmp_dir
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            # 解析 XML 输出
            external["checkstyle"] = self._parse_checkstyle_xml(result.stdout)
        except Exception as e:
            external["checkstyle"] = {"error": str(e)}

        # 2. PMD（缺陷检测）
        try:
            cmd = [
                "pmd", "check",
                "-d", tmp_dir,
                "-f", "json",
                "-R", "category/java/bestpractices.xml"  # 使用最佳实践规则集
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            external["pmd"] = json.loads(result.stdout)
        except Exception as e:
            external["pmd"] = {"error": str(e)}

        # 3. SpotBugs（需要先编译）
        try:
            # 先编译
            compile_cmd = ["javac", "-d", f"{tmp_dir}/bin"] + file_paths
            subprocess.run(compile_cmd, capture_output=True, timeout=30)

            # 运行 SpotBugs
            cmd = [
                "spotbugs", "-textui",
                "-xml:withMessages",
                f"{tmp_dir}/bin"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            external["spotbugs"] = self._parse_spotbugs_xml(result.stdout)
        except Exception as e:
            external["spotbugs"] = {"error": str(e)}

        return external
    def _run_ruff(self, cwd: str, files: List[str], timeout: int) -> Dict[str, Any]:
        """ruff 兼容旧版，使用 --output-format json"""
        # 方式1：尝试新版 --format
        code, out, err = self._run_cli_or_module(
            bin_name="ruff",
            module_name="ruff",
            args=["check", "--select", "F,E,W,B,I", "--format", "json", *files],
            timeout=timeout,
            cwd=cwd
        )

        data = []
        if out and out.strip():
            try:
                data = json.loads(out)
                if not isinstance(data, list):
                    data = []
            except Exception:
                pass

        # 如果失败且 stderr 提示不支持 --format，尝试旧版 --output-format
        if not data and ("unexpected argument" in (err or "") or "unknown option" in (err or "")):
            if DEBUG_SCANNER:
                print("[DEBUG] ruff --format 不支持，尝试 --output-format")
            code2, out2, err2 = self._run_cli_or_module(
                bin_name="ruff",
                module_name="ruff",
                args=["check", "--select", "F,E,W,B,I", "--output-format", "json", *files],
                timeout=timeout,
                cwd=cwd
            )
            if out2 and out2.strip():
                try:
                    data = json.loads(out2)
                    if not isinstance(data, list):
                        data = []
                    err = err2
                except Exception:
                    pass

        return {"count": len(data), "findings": data, "stderr": (err or "")[:400]}

    def _run_pylint(self, cwd: str, files: List[str], timeout: int) -> Dict[str, Any]:
        """pylint JSON 输出"""
        if not files:
            return {"count": 0, "findings": [], "stderr": ""}

        code, out, err = self._run_cli_or_module(
            bin_name="pylint",
            module_name="pylint",
            args=["-f", "json", "-r", "n", "--disable=all", "--enable=E,W,F", *files],
            timeout=timeout,
            cwd=cwd
        )

        data = []
        if out and out.strip():
            try:
                data = json.loads(out)
                if not isinstance(data, list):
                    data = []
            except Exception:
                pass

        return {"count": len(data), "findings": data, "stderr": (err or "")[:400]}

    def _run_mypy(self, cwd: str, files: List[str], timeout: int) -> Dict[str, Any]:
        """mypy 文本模式（最兼容）"""
        code, out, err = self._run_cli_or_module(
            bin_name="mypy",
            module_name="mypy",
            args=["--ignore-missing-imports", "--no-error-summary", *files],
            timeout=timeout,
            cwd=cwd
        )
        errors = []
        if out or err:
            combined = (out or "") + (err or "")
            for line in combined.splitlines():
                if ": error:" in line or ": warning:" in line:
                    errors.append(line.strip())
        return {"count": len(errors), "findings": errors, "stderr": (err or "")[:400]}

    def _run_bandit(self, cwd: str, timeout: int) -> Dict[str, Any]:
        """bandit JSON 输出"""
        code, out, err = self._run_cli_or_module(
            bin_name="bandit",
            module_name="bandit",
            args=["-q", "-r", cwd, "-f", "json"],
            timeout=timeout,
            cwd=cwd
        )
        bj = {}
        if out and out.strip():
            try:
                bj = json.loads(out)
            except Exception:
                bj = {}
        issues = (bj.get("results") or [])
        return {"count": len(issues), "findings": issues, "stderr": (err or "")[:400]}

    def _run_cli_or_module(self, bin_name: str, module_name: str, args: List[str],
                           timeout: int = 90, cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """优先使用 python -m，回退到直接命令"""
        cmd1 = [sys.executable, "-m", module_name, *args]
        if DEBUG_SCANNER:
            print("[DEBUG] run:", " ".join(cmd1))
        try:
            p = subprocess.run(cmd1, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            if DEBUG_SCANNER:
                print(f"[DEBUG] exit={p.returncode}, stdout_len={len(p.stdout)}, stderr_len={len(p.stderr)}")
            return p.returncode, p.stdout, p.stderr
        except Exception as e:
            if DEBUG_SCANNER:
                print(f"[DEBUG] run via -m failed: {e}")

        cmd2 = [bin_name, *args]
        if DEBUG_SCANNER:
            print("[DEBUG] run:", " ".join(cmd2))
        try:
            p = subprocess.run(cmd2, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            return p.returncode, p.stdout, p.stderr
        except Exception as e:
            return -1, "", str(e)

    # ========== 外部结果转换 ==========
    def _external_to_findings(self, external: Dict[str, Any]) -> List[Finding]:
        conv: List[Finding] = []

        # ruff
        rd = external.get("ruff", {})
        for it in (rd.get("findings") or []):
            # ✅ 规范化文件名：从完整路径提取基础文件名
            raw_filename = it.get("filename", "")
            fn = _basename(raw_filename)  # 已有的 _basename 函数

            # 🔥 调试
            if raw_filename != fn:
                if DEBUG_SCANNER:
                    print(f"[Ruff] 文件名规范化: {raw_filename} -> {fn}")

            loc = it.get("location", {}) or {}
            row = int(loc.get("row", 0) or 0)
            col = int(loc.get("column", 0) or 0)
            code = it.get("code", "RUFF")
            msg = it.get("message", "")
            sev = self._map_ruff_severity(code)
            snippet = self._get_snippet(fn, row)
            if fn:
                conv.append(Finding(fn, row, col, sev, f"RUFF-{code}", msg, snippet))

        # pylint
        pd = external.get("pylint", {})
        for it in (pd.get("findings") or []):
            # ✅ 规范化文件名
            raw_path = it.get("path", "") or it.get("filename", "")
            fn = _basename(raw_path)

            # 🔥 调试
            if raw_path != fn:
                if DEBUG_SCANNER:
                    print(f"[Pylint] 文件名规范化: {raw_path} -> {fn}")

            row = int(it.get("line", 0) or 0)
            col = int(it.get("column", 0) or 0)
            code = it.get("symbol") or it.get("message-id") or "PYLINT"
            typ = (it.get("type") or "").lower()
            sev = {"error": "HIGH", "fatal": "HIGH", "warning": "MEDIUM",
                   "convention": "LOW", "refactor": "LOW"}.get(typ, "MEDIUM")
            msg = it.get("message", "")
            snippet = self._get_snippet(fn, row)
            if fn:
                conv.append(Finding(fn, row, col, sev, f"PL-{code}", msg, snippet))

        # mypy
        md = external.get("mypy", {})
        for line in (md.get("findings") or []):
            # 解析格式：filename:line:col: error: message
            m = re.match(r"(.+?):(\d+):(\d+):\s+(error|warning):\s+(.+)", line)
            if not m:
                m = re.match(r"(.+?):(\d+):\s+(error|warning):\s+(.+)", line)
                if m:
                    raw_fn, row, typ, msg = m.groups()
                    col = 0
                else:
                    continue
            else:
                raw_fn, row, col, typ, msg = m.groups()

            # ✅ 规范化文件名
            fn = _basename(raw_fn)

            # 🔥 调试
            if raw_fn != fn:
                if DEBUG_SCANNER:
                    print(f"[Mypy] 文件名规范化: {raw_fn} -> {fn}")

            sev = "HIGH" if typ == "error" else "MEDIUM"
            snippet = self._get_snippet(fn, int(row))
            conv.append(Finding(fn, int(row), int(col) if col else 0, sev, "MYPY", msg, snippet))

        # bandit
        bd = external.get("bandit", {})
        for it in (bd.get("findings") or []):
            # ✅ 规范化文件名
            raw_filename = it.get("filename", "")
            fn = _basename(raw_filename)

            # 🔥 调试
            if raw_filename != fn:
                if DEBUG_SCANNER:
                    print(f"[Bandit] 文件名规范化: {raw_filename} -> {fn}")

            row = int(it.get("line_number", 0) or 0)
            code = it.get("test_id", "BANDIT")
            sev0 = (it.get("issue_severity") or "").upper()
            sev = {"HIGH": "HIGH", "MEDIUM": "MEDIUM"}.get(sev0, "LOW")
            msg = it.get("issue_text", "")
            snippet = self._get_snippet(fn, row)
            if fn:
                conv.append(Finding(fn, row, 0, sev, code, msg, snippet))

        return conv

    def _map_ruff_severity(self, code: str) -> str:
        if not code:
            return "LOW"
        head = code[:1]
        if head in ("F", "E"):
            return "HIGH"
        if head in ("W",):
            return "MEDIUM"
        return "LOW"

    def _get_snippet(self, basename: str, line: int) -> str:
        src = self.file_map.get(basename, "")
        if not src or line <= 0:
            return ""
        lines = src.splitlines()
        idx = min(max(line - 1, 0), len(lines) - 1)
        return lines[idx] if idx < len(lines) else ""

    # ========== 动态检测 ==========
    def run_dynamic_light(self, tmp_dir: str, timeout_sec: int = 10) -> Dict[str, Any]:
        summary: Dict[str, Any] = {"py_compile": []}

        py_files: List[str] = []
        for root, _, files in os.walk(tmp_dir):
            for fn in files:
                if fn.endswith(".py"):
                    py_files.append(os.path.join(root, fn))

        def _compile_one(fp):
            try:
                py_compile.compile(fp, doraise=True)
                return None
            except py_compile.PyCompileError as e:
                return {"file": os.path.basename(fp), "error": str(e)}

        with ThreadPoolExecutor(max_workers=min(8, max(2, (os.cpu_count() or 2)))) as ex:
            futures = {ex.submit(_compile_one, f): f for f in py_files}
            for fu in as_completed(futures):
                try:
                    err = fu.result()
                    if err:
                        summary["py_compile"].append(err)
                except Exception:
                    pass

        summary["pytest"] = {"skipped": True, "reason": "未配置测试"}
        return summary


def summarize_findings(result: Dict[str, Any], top_k: int = 30) -> str:
    """生成摘要报告"""
    lines = []
    builtin = result.get("static_builtin", [])
    external = result.get("external", {})

    if builtin:
        lines.append(f"发现 {len(builtin)} 个静态问题：")
        severity_count = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in builtin:
            sev = f.get("severity", "LOW")
            severity_count[sev] = severity_count.get(sev, 0) + 1

        lines.append(f"- 高危：{severity_count['HIGH']} 个")
        lines.append(f"- 中危：{severity_count['MEDIUM']} 个")
        lines.append(f"- 低危：{severity_count['LOW']} 个")

        sorted_findings = sorted(builtin, key=lambda x: (
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x.get("severity"), 9),
            x.get("file", ""),
            x.get("line", 0)
        ))

        lines.append(f"\n前 {min(top_k, len(sorted_findings))} 个问题：")
        for i, f in enumerate(sorted_findings[:top_k], 1):
            lines.append(f"{i:02d}. [{f.get('severity', 'LOW')}] {f.get('rule_id', 'UNKNOWN')} "
                         f"{f.get('file', 'unknown')}:{f.get('line', 0)} - {f.get('message', '')}")
    else:
        lines.append("未发现静态问题。")

    if external:
        lines.append(f"\n外部工具执行情况：")
        for tool, data in external.items():
            if isinstance(data, dict):
                if "error" in data:
                    lines.append(f"- {tool}: 错误 - {data['error'][:100]}")
                else:
                    count = data.get("count", 0)
                    lines.append(f"- {tool}: {count} 个问题")

    return "\n".join(lines)