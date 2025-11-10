# fixers/java_fixer.py
"""
JavaFixer - Java代码修复器
"""
import re
from typing import Dict, List, Any

from .base_fixer import BaseFixer, FixResult, Language


class JavaFixer(BaseFixer):
    """Java专用修复器"""

    def __init__(self, llm_client=None, prompt_config: Dict[str, Any] = None):
        super().__init__(Language.JAVA, llm_client)
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

        print(f"[JavaFixer] 开始规则修复: {filename}")
        print(f"[JavaFixer] 待修复问题数: {len(issues)}")

        # 规则1: System.out.println -> logger
        logger_issues = [issue for issue in issues if "System.out.println" in issue.get("message", "")]
        if logger_issues:
            print(f"[JavaFixer] 修复 System.out.println: {len(logger_issues)} 处")
            new_content, count = self._fix_system_out_println(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(logger_issues)

        # 规则2: == 比较字符串 -> equals()
        string_compare_issues = [issue for issue in issues
                                 if "==" in issue.get("message", "") or "string comparison" in issue.get("message", "").lower()]
        if string_compare_issues:
            print(f"[JavaFixer] 修复字符串比较: {len(string_compare_issues)} 处")
            new_content, count = self._fix_string_comparison(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(string_compare_issues)

        # 规则3: 资源未关闭 -> try-with-resources
        resource_issues = [issue for issue in issues
                           if "resource" in issue.get("message", "").lower() or "close" in issue.get("message", "").lower()]
        if resource_issues:
            print(f"[JavaFixer] 修复资源泄漏: {len(resource_issues)} 处")
            new_content, count = self._fix_resource_leak(fixed_content)
            if count > 0:
                fixed_content = new_content
                fixed_count += count
                fixed_issues.extend(resource_issues)

        print(f"[JavaFixer] 规则修复完成: 修复了 {fixed_count} 处问题")

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

    def _fix_system_out_println(self, content: str) -> tuple:
        """修复 System.out.println"""
        count = 0
        lines = content.split('\n')

        # 检查是否已有logger
        has_logger = any("Logger" in line and "logger" in line.lower() for line in lines)

        if not has_logger:
            # 添加logger导入和声明
            for i, line in enumerate(lines):
                if line.strip().startswith("import ") and "java" in line:
                    if not any("slf4j" in l for l in lines[:i + 1]):
                        lines.insert(i + 1, "import org.slf4j.Logger;")
                        lines.insert(i + 2, "import org.slf4j.LoggerFactory;")
                        break

            # 添加logger字段
            for i, line in enumerate(lines):
                if re.search(r'public\s+class\s+(\w+)', line):
                    class_name = re.search(r'class\s+(\w+)', line).group(1)
                    logger_line = f"    private static final Logger logger = LoggerFactory.getLogger({class_name}.class);"
                    if i + 1 < len(lines) and '{' in lines[i]:
                        lines.insert(i + 1, logger_line)
                    elif i + 1 < len(lines):
                        lines.insert(i + 2, logger_line)
                    break

        # 替换 System.out.println
        for i, line in enumerate(lines):
            if "System.out.println" in line:
                new_line = re.sub(
                    r'System\.out\.println\s*\((.*?)\)',
                    r'logger.info(\1)',
                    line
                )
                if new_line != line:
                    lines[i] = new_line
                    count += 1

        return '\n'.join(lines), count

    def _fix_string_comparison(self, content: str) -> tuple:
        """修复字符串比较"""
        count = 0

        # str1 == "xxx" -> str1.equals("xxx")
        pattern1 = r'(\w+)\s*==\s*("(?:[^"\\]|\\.)*")'
        new_content = re.sub(pattern1, r'\1.equals(\2)', content)
        count += len(re.findall(pattern1, content))

        # "xxx" == str1 -> "xxx".equals(str1)
        pattern2 = r'("(?:[^"\\]|\\.)*")\s*==\s*(\w+)'
        new_content = re.sub(pattern2, r'\1.equals(\2)', new_content)
        count += len(re.findall(pattern2, new_content))

        # str1 == str2 -> str1.equals(str2)
        pattern3 = r'(\w+)\s*==\s*(\w+)(?=\s*[;)])'
        matches = re.findall(pattern3, new_content)
        for match in matches:
            if not any(keyword in match[0] for keyword in ['int', 'boolean', 'long', 'double']):
                new_content = new_content.replace(f"{match[0]} == {match[1]}", f"{match[0]}.equals({match[1]})")
                count += 1

        return new_content, count

    def _fix_resource_leak(self, content: str) -> tuple:
        """修复资源泄漏"""
        count = 0
        lines = content.split('\n')
        new_lines = []

        i = 0
        while i < len(lines):
            line = lines[i]

            resource_pattern = r'(\w+)\s+(\w+)\s*=\s*new\s+(FileInputStream|BufferedReader|FileWriter|Scanner)\s*\('
            match = re.search(resource_pattern, line)

            if match and 'try' not in line:
                resource_name = match.group(2)

                # 查找是否有对应的 close()
                has_close = False
                for j in range(i + 1, min(i + 20, len(lines))):
                    if f"{resource_name}.close()" in lines[j]:
                        has_close = True
                        break

                if not has_close:
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(' ' * indent + f"try ({line.strip()}")
                    new_lines.append(' ' * indent + '{')
                    count += 1
                    i += 1
                    continue

            new_lines.append(line)
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
            print(f"[JavaFixer] LLM客户端未配置")
            return result

        print(f"[JavaFixer] 开始LLM修复: {filename}")
        print(f"[JavaFixer] 问题数: {len(issues)}")

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

            print(f"[JavaFixer] 调用LLM API...")
            response = self.llm_client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )

            print(f"[JavaFixer] LLM响应长度: {len(response)} 字符")

            fixed_code = self._extract_code_from_response(response, filename)

            if fixed_code and fixed_code != content:
                result.fixed_content = fixed_code
                result.fixed_count = len(issues)
                result.success = True
                print(f"[JavaFixer] LLM修复成功")
            else:
                result.error_message = "LLM未返回有效的修复代码"
                print(f"[JavaFixer] LLM修复失败: 未返回有效代码")

        except Exception as e:
            result.error_message = f"LLM调用失败: {str(e)}"
            print(f"[JavaFixer] LLM调用异常: {e}")
            import traceback
            traceback.print_exc()

        return result

    def _build_system_prompt(self) -> str:
        """✅ 构建LLM系统提示词（标准化）"""
        lang = self.prompt_conf.get("language", "zh")
        style = self.prompt_conf.get("style", "concise")
        return (
            f"你是专业的 Java 代码修复助手。请严格遵守：\n"
            f"1) 仅输出完整的代码，不要输出解释。\n"
            f"2) 输出格式必须为一个带文件名的 java 代码块：```java <相对路径或文件名>.java\\n<完整代码>```\n"
            f"3) 不要输出 diff、不要输出多余文本或多个代码块。\n"
            f"4) 如果无法修复，请也输出原样的完整文件代码块。\n"
            f"5) 确保修复后的代码可以编译通过，添加必要的导入语句。\n"
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
        issue_text = "\n".join(issue_lines) if issue_lines else "无结构化缺陷条目。"

        strict_hint = (
            "【重要】只输出一个带文件名的 java 代码块，不要任何说明文字、不要 diff。"
            if force_code_block_only else
            "如果可能，只输出一个带文件名的 java 代码块；不要输出 diff 或解释。"
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
            f"```java {filename}\n<完整代码>\n```\n"
        )

    def _extract_code_from_response(self, response: str, expected_filename: str) -> str:
        """从LLM响应中提取代码"""
        # ✅ 匹配 ```java filename.java
        pattern = r"```java\s+([^\n]+)?\s*\n(.*?)```"
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

        if matches:
            for match in matches:
                code = match[1] if len(match) > 1 else match[0]
                if code.strip():
                    return code.strip()

        # 提取任何Java代码块
        pattern = r"```java\s*\n(.*?)```"
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
        fixable_rules = ["JAVA002", "JAVA003", "JAVA004"]
        return rule_id in fixable_rules