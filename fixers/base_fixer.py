# fixers/base_fixer.py
"""
BaseFixer - 所有语言修复器的基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.common import FixResult
from utils.language_detector import Language


class BaseFixer(ABC):
    """修复器基类"""

    def __init__(self, language: Language, llm_client=None):
        """
        Args:
            language: 目标语言
            llm_client: LLM客户端（用于LLM修复）
        """
        self.language = language
        self.llm_client = llm_client
        self.fixed_files = []

    @abstractmethod
    def apply_rule_fixes(self, file: Dict[str, Any], issues: List[Dict]) -> FixResult:
        """
        应用规则化修复（必须实现）

        Args:
            file: {"file": "xxx", "content": "..."}
            issues: [{"rule_id": "XXX001", "line": 10, "message": "...", ...}, ...]

        Returns:
            FixResult对象
        """
        pass

    @abstractmethod
    def apply_llm_fixes(self, file: Dict[str, Any], issues: List[Dict],
                        user_request: str = "") -> FixResult:
        """
        应用LLM修复（必须实现）

        Args:
            file: {"file": "xxx", "content": "..."}
            issues: 剩余未修复的问题列表
            user_request: 用户额外的修复请求

        Returns:
            FixResult对象
        """
        pass

    def fix(self, file: Dict[str, Any], issues: List[Dict],
            use_rules: bool = True, use_llm: bool = True,
            user_request: str = "") -> FixResult:
        """
        完整修复流程：先规则后LLM

        Args:
            file: 文件信息
            issues: 问题列表
            use_rules: 是否使用规则修复
            use_llm: 是否使用LLM修复
            user_request: 用户额外请求

        Returns:
            FixResult对象
        """
        filename = file.get("file", "")
        original_content = file.get("content", "")

        result = FixResult(
            file=filename,
            language=self.language.value,
            original_content=original_content,
            fixed_content=original_content,
            fixed_count=0,
            method="none",
            success=False
        )

        remaining_issues = issues.copy()

        # 1. 规则化修复
        if use_rules and remaining_issues:
            try:
                rule_result = self.apply_rule_fixes(file, remaining_issues)
                if rule_result.fixed_count > 0:
                    result.fixed_content = rule_result.fixed_content
                    result.fixed_count += rule_result.fixed_count
                    result.method = "rule"
                    result.success = True

                    # 更新文件内容供后续处理
                    file = file.copy()
                    file["content"] = rule_result.fixed_content

                    # 过滤已修复的问题（简化处理）
                    remaining_issues = [
                        issue for issue in remaining_issues
                        if self._is_rule_fixable(issue.get("rule_id", ""))
                    ]
            except Exception as e:
                result.error_message = f"规则修复失败: {str(e)}"

        # 2. LLM修复（处理剩余问题）
        if use_llm and self.llm_client and remaining_issues:
            try:
                llm_result = self.apply_llm_fixes(file, remaining_issues, user_request)
                if llm_result.success:
                    result.fixed_content = llm_result.fixed_content
                    result.fixed_count += llm_result.fixed_count
                    result.method = "rule+llm" if result.method == "rule" else "llm"
                    result.success = True
            except Exception as e:
                if result.method == "none":
                    result.error_message = f"LLM修复失败: {str(e)}"
                else:
                    result.error_message += f"; LLM修复失败: {str(e)}"

        return result

    def _is_rule_fixable(self, rule_id: str) -> bool:
        """判断规则是否可以自动修复（子类可重写）"""
        return False

    def _build_llm_system_prompt(self) -> str:
        """构建LLM系统提示（子类可重写）"""
        lang_name = self.language.value.capitalize()
        return (
            f"你是专业的{lang_name}代码修复助手。请严格遵守：\n"
            f"1) 自动识别并修复代码中的bug和问题\n"
            f"2) 仅输出完整的修复后代码，不要输出解释\n"
            f"3) 输出格式必须为带文件名的代码块：```{self.language.value} <文件名>\\n<完整代码>```\n"
            f"4) 如果无法修复，输出原样代码块\n"
            f"5) 保持代码的原有结构和风格\n"
        )

    def _build_llm_user_prompt(self, filename: str, content: str,
                               issues: List[Dict], user_request: str = "") -> str:
        """构建LLM用户提示（子类可重写）"""
        issue_lines = []
        for it in issues[:20]:  # 限制数量
            issue_lines.append(
                f"- [{it.get('rule_id', '')}] 行 {it.get('line', '?')}: {it.get('message', '')}"
            )
        issue_text = "\n".join(issue_lines) if issue_lines else "无结构化缺陷条目。"

        prompt = (
            f"请修复下述{self.language.value.upper()}文件中的问题，并返回修复后的完整源代码。\n\n"
            f"【目标文件】{filename}\n"
            f"【检测到的问题】\n{issue_text}\n"
        )

        if user_request:
            prompt += f"【用户额外要求】\n{user_request}\n\n"

        prompt += (
            f"【原始代码开始】\n{content}\n【原始代码结束】\n\n"
            f"只输出一个带文件名的{self.language.value}代码块，格式：\n"
            f"```{self.language.value} {filename}\n<完整代码>\n```\n"
        )

        return prompt