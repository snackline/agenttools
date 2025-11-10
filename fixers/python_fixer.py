# fixers/python_fixer.py
"""
PythonFixer - Python代码修复器
"""
import re
from typing import Dict, List, Any, Union

from .base_fixer import BaseFixer, FixResult, Language


class PythonFixer(BaseFixer):
    """Python专用修复器"""

    def __init__(self, llm_client=None, prompt_config: Dict[str, Any] = None):
        super().__init__(Language.PYTHON, llm_client)
        # ✅ 添加 prompt 配置
        self.prompt_conf = prompt_config or {
            "language": "zh",
            "style": "concise",
            "force_code_block_only": True
        }

    def apply_rule_fixes(self, file: Dict[str, Any], issues: List[Union[Dict, str]]) -> FixResult:
        """应用规则化修复"""
        filename = file.get("file", "")
        content = file.get("content", "")
        fixed_content = content
        fixed_count = 0

        print(f"[PythonFixer] 开始规则修复: {filename}")
        print(f"[PythonFixer] 待修复问题数: {len(issues)}")

        # ✅ 规范化 issues 格式
        normalized_issues = self._normalize_issues(issues)

        # 规则1: xrange -> range (Python 2 to 3)
        if any(issue.get("rule_id") == "PY201" for issue in normalized_issues):
            new_content = re.sub(r'\bxrange\b', 'range', fixed_content)
            if new_content != fixed_content:
                fixed_content = new_content
                fixed_count += 1

        # 规则2: raw_input -> input (Python 2 to 3)
        if any(issue.get("rule_id") == "PY203" for issue in normalized_issues):
            new_content = re.sub(r'\braw_input\b', 'input', fixed_content)
            if new_content != fixed_content:
                fixed_content = new_content
                fixed_count += 1

        # 规则3: except Exception, e -> except Exception as e
        if any("except" in str(issue).lower() and "," in str(issue) for issue in normalized_issues):
            pattern = r'except\s+(\w+)\s*,\s*(\w+)'
            new_content = re.sub(pattern, r'except \1 as \2', fixed_content)
            if new_content != fixed_content:
                fixed_content = new_content
                fixed_count += 1

        # 规则4: print "xxx" -> print("xxx")
        if any("print" in str(issue).lower() for issue in normalized_issues):
            pattern = r'print\s+"([^"]*)"'
            new_content = re.sub(pattern, r'print("\1")', fixed_content)
            if new_content != fixed_content:
                fixed_content = new_content
                fixed_count += 1

        # ✅ 规则5: 修复常见的 pylint/flake8 问题
        fixed_content, additional_fixes = self._apply_common_fixes(fixed_content, normalized_issues)
        fixed_count += additional_fixes

        print(f"[PythonFixer] 规则修复完成: 修复了 {fixed_count} 处问题")

        return FixResult(
            file=filename,
            language=self.language.value,
            original_content=content,
            fixed_content=fixed_content,
            fixed_count=fixed_count,
            method="rule",
            success=fixed_count > 0,
            error_message="" if fixed_count > 0 else "没有找到可自动修复的问题"
        )

    def _normalize_issues(self, issues: List[Union[Dict, str]]) -> List[Dict]:
        """规范化 issues 格式"""
        normalized = []
        for issue in issues:
            if isinstance(issue, dict):
                normalized.append(issue)
            elif isinstance(issue, str):
                parsed = self._parse_issue_string(issue)
                normalized.append(parsed)
            else:
                normalized.append({
                    "type": "unknown",
                    "message": str(issue),
                    "rule_id": "UNKNOWN"
                })
        return normalized

    def _parse_issue_string(self, issue_str: str) -> Dict[str, Any]:
        """解析字符串格式的问题"""
        # 正则匹配：文件名:行号:列号: 错误码 消息
        pattern1 = r'^([^:]+):(\d+):(\d+):\s*([A-Z]\d+)\s+(.+)$'
        match = re.match(pattern1, issue_str)
        if match:
            return {
                "file": match.group(1),
                "line": int(match.group(2)),
                "column": int(match.group(3)),
                "rule_id": match.group(4),
                "message": match.group(5),
                "severity": self._get_severity_from_code(match.group(4))
            }

        # 正则匹配：文件名:行号: 错误码 消息
        pattern2 = r'^([^:]+):(\d+):\s*([A-Z]\d+)\s+(.+)$'
        match = re.match(pattern2, issue_str)
        if match:
            return {
                "file": match.group(1),
                "line": int(match.group(2)),
                "rule_id": match.group(3),
                "message": match.group(4),
                "severity": self._get_severity_from_code(match.group(3))
            }

        # 无法解析，返回原始字符串
        return {
            "type": "unknown",
            "message": issue_str,
            "rule_id": "UNKNOWN",
            "severity": "MEDIUM"
        }

    def _get_severity_from_code(self, code: str) -> str:
        """根据错误码判断严重程度"""
        if code.startswith('E'):
            return 'HIGH'
        elif code.startswith('W'):
            return 'MEDIUM'
        return 'LOW'

    def _apply_common_fixes(self, content: str, issues: List[Dict]) -> tuple:
        """应用常见的自动修复"""
        fixed_content = content
        fix_count = 0

        # 修复1: 移除行尾空格 (W291)
        if any(issue.get("rule_id") == "W291" for issue in issues):
            new_content = re.sub(r'[ \t]+$', '', fixed_content, flags=re.MULTILINE)
            if new_content != fixed_content:
                fixed_content = new_content
                fix_count += 1

        # 修复2: 移除多余的空行 (W391)
        if any(issue.get("rule_id") == "W391" for issue in issues):
            new_content = fixed_content.rstrip() + '\n'
            if new_content != fixed_content:
                fixed_content = new_content
                fix_count += 1

        return fixed_content, fix_count

    def apply_llm_fixes(self, file: Dict[str, Any], issues: List[Union[Dict, str]],
                        user_request: str = "") -> FixResult:
        """应用LLM修复"""
        filename = file.get("file", "")
        content = file.get("content", "")

        result = FixResult(
            file=filename,
            language=self.language.value,
            original_content=content,
            fixed_content=content,
            fixed_count=0,
            method="llm",
            success=False
        )

        if not self.llm_client:
            result.error_message = "LLM客户端未配置"
            print(f"[PythonFixer] LLM客户端未配置")
            return result

        print(f"[PythonFixer] 开始LLM修复: {filename}")
        print(f"[PythonFixer] 问题数: {len(issues)}")

        try:
            # ✅ 规范化 issues
            normalized_issues = self._normalize_issues(issues)

            # ✅ 使用标准化的 prompt 构建方法
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(
                filename=filename,
                original_content=content,
                issues=normalized_issues,
                user_request=user_request,
                force_code_block_only=self.prompt_conf.get("force_code_block_only", True)
            )

            print(f"[PythonFixer] 调用LLM API...")

            # ✅ 调用LLM（兼容两种客户端）
            if hasattr(self.llm_client, 'chat') and callable(self.llm_client.chat):
                response = self.llm_client.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=4000
                )
            else:
                result.error_message = "不支持的LLM客户端类型"
                return result

            print(f"[PythonFixer] LLM响应长度: {len(response)} 字符")

            # 解析响应
            fixed_code = self._extract_code_from_response(response, filename)

            if fixed_code and fixed_code != content:
                result.fixed_content = fixed_code
                result.fixed_count = len(normalized_issues)
                result.success = True
                print(f"[PythonFixer] LLM修复成功")
            else:
                result.error_message = "LLM未返回有效的修复代码"
                print(f"[PythonFixer] LLM修复失败: 未返回有效代码")

        except Exception as e:
            result.error_message = f"LLM调用失败: {str(e)}"
            print(f"[PythonFixer] LLM调用异常: {e}")
            import traceback
            traceback.print_exc()

        return result

    def _build_system_prompt(self) -> str:
        """✅ 构建LLM系统提示词（标准化）"""
        lang = self.prompt_conf.get("language", "zh")
        style = self.prompt_conf.get("style", "concise")
        return (
            f"你是专业的 Python 代码修复助手。请严格遵守：\n"
            f"1) 仅输出完整的代码，不要输出解释。\n"
            f"2) 输出格式必须为一个带文件名的 python 代码块：```python <相对路径或文件名>.py\\n<完整代码>```\n"
            f"3) 不要输出 diff、不要输出多余文本或多个代码块。\n"
            f"4) 如果无法修复，请也输出原样的完整文件代码块。\n"
            f"语言：{lang}；风格：{style}。\n"
        )

    def _build_user_prompt(
        self,
        filename: str,
        original_content: str,
        issues: List[Dict[str, Any]],
        user_request: str,
        force_code_block_only: bool
    ) -> str:
        """✅ 构建LLM用户提示词（标准化）"""
        issue_lines = []
        for it in issues:
            issue_lines.append(
                f"- [{it.get('rule_id','')}] 行 {it.get('line','?')}: {it.get('message','')}"
            )
        issue_text = "\n".join(issue_lines) if issue_lines else "无结构化缺陷条目（可能是外部工具或动态问题）。"

        strict_hint = (
            "【重要】只输出一个带文件名的 python 代码块，不要任何说明文字、不要 diff。"
            if force_code_block_only else
            "如果可能，只输出一个带文件名的 python 代码块；不要输出 diff 或解释。"
        )

        extra = f"\n【用户补充需求】\n{user_request}\n" if user_request else ""

        return (
            f"请修复下述文件中的问题，并返回修复后的完整源代码。\n\n"
            f"【目标文件】{filename}\n"
            f"【检测到的问题】\n{issue_text}\n"
            f"{extra}\n"
            f"【原始代码开始】\n{original_content}\n【原始代码结束】\n\n"
            f"{strict_hint}\n"
            f"代码块格式示例：\n"
            f"```python {filename}\n<完整代码>\n```\n"
        )

    def _extract_code_from_response(self, response: str, expected_filename: str) -> str:
        """从LLM响应中提取代码"""
        # ✅ 匹配 ```python filename.py 或 ```py filename.py
        pattern = r"```(?:python|py)\s+([^\n]+)\s*\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

        for filename, code in matches:
            filename = filename.strip()
            # 检查文件名是否匹配
            if filename in expected_filename or expected_filename in filename:
                return code.strip()

        # 如果没有匹配，尝试提取任何Python代码块
        pattern = r"```(?:python|py)\s*\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        if matches:
            return matches[0].strip()

        return ""

    def _is_rule_fixable(self, rule_id: str) -> bool:
        """判断规则是否可以自动修复"""
        fixable_rules = [
            "PY201", "PY203",
            "W291", "W391",
            "E111", "E117",
            "E302", "E305",
        ]
        return rule_id in fixable_rules