# fixers/cpp_fixer.py
"""
CppFixer - C/C++代码修复器
"""
import re
from typing import Dict, List, Any

from .base_fixer import BaseFixer, FixResult, Language


class CppFixer(BaseFixer):
    """C/C++专用修复器"""

    def __init__(self, llm_client=None, language: Language = Language.CPP, prompt_config: Dict[str, Any] = None):
        super().__init__(language, llm_client)
        # ✅ 添加 prompt 配置
        self.prompt_conf = prompt_config or {
            "language": "zh",
            "style": "concise",
            "force_code_block_only": True
        }

    def apply_rule_fixes(self, file: Dict[str, Any], issues: List[Dict]) -> FixResult:
        """应用规则化修复"""
        filename = file.get("file", "")
        content = file.get("content", "")
        fixed_content = content
        fixed_count = 0
        fixed_issues = []

        print(f"[CppFixer] 开始规则修复: {filename}")
        print(f"[CppFixer] 待修复问题数: {len(issues)}")

        # 规则1: gets() -> fgets()
        gets_issues = [issue for issue in issues if "gets" in issue.get("message", "").lower()]
        if gets_issues:
            print(f"[CppFixer] 修复 gets(): {len(gets_issues)} 处")
            new_content, count = self._fix_gets(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(gets_issues)

        # 规则2: strcpy() -> strncpy()
        strcpy_issues = [issue for issue in issues if "strcpy" in issue.get("message", "").lower()]
        if strcpy_issues:
            print(f"[CppFixer] 修复 strcpy(): {len(strcpy_issues)} 处")
            new_content, count = self._fix_strcpy(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(strcpy_issues)

        # 规则3: 空指针检查
        null_issues = [issue for issue in issues
                       if "null" in issue.get("message", "").lower() or "nullptr" in issue.get("message", "").lower()]
        if null_issues:
            print(f"[CppFixer] 添加空指针检查: {len(null_issues)} 处")
            new_content, count = self._fix_null_check(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(null_issues)

        print(f"[CppFixer] 规则修复完成: 修复了 {fixed_count} 处问题")

        return FixResult(
            file=filename,
            language=self.language.value,
            original_content=content,
            fixed_content=fixed_content,
            fixed_count=fixed_count,
            method="rule",
            success=fixed_count > 0,
            fixed_issues=fixed_issues
        )

    def _fix_gets(self, content: str) -> tuple:
        """修复 gets()"""
        count = 0
        # gets(buf) -> fgets(buf, sizeof(buf), stdin)
        pattern = r'\bgets\s*\(\s*(\w+)\s*\)'
        matches = re.findall(pattern, content)
        count = len(matches)

        if count > 0:
            content = re.sub(
                pattern,
                r'fgets(\1, sizeof(\1), stdin)',
                content
            )

        return content, count

    def _fix_strcpy(self, content: str) -> tuple:
        """修复 strcpy()"""
        count = 0
        # strcpy(dest, src) -> strncpy(dest, src, sizeof(dest))
        pattern = r'\bstrcpy\s*\(\s*(\w+)\s*,\s*([^)]+)\s*\)'
        matches = re.findall(pattern, content)
        count = len(matches)

        if count > 0:
            content = re.sub(
                pattern,
                r'strncpy(\1, \2, sizeof(\1) - 1)',
                content
            )

        return content, count

    def _fix_null_check(self, content: str) -> tuple:
        """添加空指针检查"""
        count = 0
        lines = content.split('\n')
        new_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]
            new_lines.append(line)

            # 检测指针分配模式
            malloc_pattern = r'(\w+)\s*=\s*(malloc|calloc|realloc)\s*\('
            match = re.search(malloc_pattern, line)

            if match:
                ptr_name = match.group(1)

                # 检查是否已有null检查
                has_check = False
                for j in range(i + 1, min(i + 5, len(lines))):
                    if f"{ptr_name}" in lines[j] and ("NULL" in lines[j] or "nullptr" in lines[j]):
                        has_check = True
                        break

                if not has_check:
                    indent = len(line) - len(line.lstrip())
                    null_check = ' ' * indent + f'if ({ptr_name} == NULL) {{'
                    error_handle = ' ' * (indent + 4) + 'fprintf(stderr, "Memory allocation failed\\n");'
                    return_line = ' ' * (indent + 4) + 'return;'
                    close_brace = ' ' * indent + '}'

                    new_lines.extend([null_check, error_handle, return_line, close_brace])
                    count += 1

            i += 1

        return '\n'.join(new_lines), count

    def apply_llm_fixes(self, file: Dict[str, Any], issues: List[Dict],
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
            print(f"[CppFixer] LLM客户端未配置")
            return result

        print(f"[CppFixer] 开始LLM修复: {filename}")
        print(f"[CppFixer] 问题数: {len(issues)}")

        try:
            # ✅ 使用标准化的 prompt 构建方法
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(
                filename=filename,
                original_content=content,
                issues=issues,
                user_request=user_request,
                force_code_block_only=self.prompt_conf.get("force_code_block_only", True)
            )

            print(f"[CppFixer] 调用LLM API...")
            response = self.llm_client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )

            print(f"[CppFixer] LLM响应长度: {len(response)} 字符")

            fixed_code = self._extract_code_from_response(response, filename)

            if fixed_code and fixed_code != content:
                result.fixed_content = fixed_code
                result.fixed_count = len(issues)
                result.success = True
                print(f"[CppFixer] LLM修复成功")
            else:
                result.error_message = "LLM未返回有效的修复代码"
                print(f"[CppFixer] LLM修复失败: 未返回有效代码")

        except Exception as e:
            result.error_message = f"LLM调用失败: {str(e)}"
            print(f"[CppFixer] LLM调用异常: {e}")
            import traceback
            traceback.print_exc()

        return result

    def _build_system_prompt(self) -> str:
        """✅ 构建LLM系统提示词（标准化）"""
        lang = self.prompt_conf.get("language", "zh")
        style = self.prompt_conf.get("style", "concise")
        lang_name = "C++" if self.language == Language.CPP else "C"
        lang_ext = "cpp" if self.language == Language.CPP else "c"

        return (
            f"你是专业的 {lang_name} 代码修复助手。请严格遵守：\n"
            f"1) 仅输出完整的代码，不要输出解释。\n"
            f"2) 输出格式必须为一个带文件名的 {lang_ext} 代码块：```{lang_ext} <相对路径或文件名>.{lang_ext}\\n<完整代码>```\n"
            f"3) 不要输出 diff、不要输出多余文本或多个代码块。\n"
            f"4) 如果无法修复，请也输出原样的完整文件代码块。\n"
        f"5) 优先修复安全问题（缓冲区溢出、空指针、内存泄漏）。\n"
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
            lang_ext = "cpp" if self.language == Language.CPP else "c"

            issue_lines = []
            for it in issues:
                issue_lines.append(
                    f"- [{it.get('rule_id', '')}] 行 {it.get('line', '?')}: {it.get('message', '')}"
                )
            issue_text = "\n".join(issue_lines) if issue_lines else "无结构化缺陷条目。"

            strict_hint = (
                f"【重要】只输出一个带文件名的 {lang_ext} 代码块，不要任何说明文字、不要 diff。"
                if force_code_block_only else
                f"如果可能，只输出一个带文件名的 {lang_ext} 代码块；不要输出 diff 或解释。"
            )

            extra = f"\n【用户补充需求】\n{user_request}\n" if user_request else ""

            return (
                f"请修复下述文件中的安全问题，并返回修复后的完整源代码。\n\n"
            f"【目标文件】{filename}\n"
            f"【检测到的问题】\n{issue_text}\n"
            f"{extra}\n"
            f"【原始代码开始】\n{original_content}\n【原始代码结束】\n\n"
            f"{strict_hint}\n"
            f"代码块格式示例：\n"
            f"```{lang_ext} {filename}\n<完整代码>\n```\n"
            )

            def _extract_code_from_response(self, response: str, expected_filename: str) -> str:
                """从LLM响应中提取代码"""
                lang_tag = self.language.value

                # ✅ 匹配 ```cpp 或 ```c
                pattern = rf"```{lang_tag}\s+([^\n]+)?\s*\n(.*?)```"
                matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

                if matches:
                    for match in matches:
                        code = match[1] if len(match) > 1 else match[0]
                        if code.strip():
                            return code.strip()

                # 提取任何C/C++代码块
                pattern = rf"```(?:cpp|c)\s*\n(.*?)```"
                matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
                if matches:
                    return matches[0].strip()

                # 提取任何代码块
                pattern = r"```\s*\n(.*?)```"
                matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
                if matches:
                    return matches[0].strip()

                return ""

            def _is_rule_fixable(self, rule_id: str) -> bool:
                """判断规则是否可以自动修复"""
                fixable_rules = ["CPP001", "CPP002", "CPP003", "CPP004"]
                return rule_id in fixable_rules