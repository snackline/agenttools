# -- coding: utf-8 --
"""
ReportGenerator - 缺陷检测与修复报告生成器
支持：Markdown、HTML、JSON 格式
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List


class ReportGenerator:
    def __init__(self, scan_result: Dict[str, Any], fix_result: Dict[str, Any],
                 verify_result: Dict[str, Any]):
        self.scan_result = scan_result or {}
        self.fix_result = fix_result or {}
        self.verify_result = verify_result or {}
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def generate_markdown(self, output_path: str = None) -> str:
        """生成 Markdown 报告"""
        lines = []

        # 标题
        lines.append("# 🔍 代码缺陷检测与修复报告")
        lines.append(f"\n**生成时间**: {self.timestamp}\n")
        lines.append("---\n")

        # 1. 执行摘要
        lines.append("## 📊 执行摘要\n")

        static_defects = self.scan_result.get("static_builtin", [])
        dynamic_data = self.scan_result.get("dynamic", {})
        external_data = self.scan_result.get("external", {})

        # 按严重性统计
        high = sum(1 for d in static_defects if d.get("severity") == "HIGH")
        medium = sum(1 for d in static_defects if d.get("severity") == "MEDIUM")
        low = sum(1 for d in static_defects if d.get("severity") == "LOW")

        # 动态检测
        compile_errors = len(dynamic_data.get("py_compile", []))

        # 外部工具统计
        external_count = 0
        for tool in ["ruff", "pylint", "mypy", "bandit"]:
            tool_data = external_data.get(tool, {})
            if isinstance(tool_data, dict):
                external_count += tool_data.get("count", 0)

        lines.append("### 🎯 总体情况\n")
        lines.append(f"- **静态分析（内置规则）**: {len(static_defects)} 个")
        lines.append(f"  - 🔴 高危: {high} 个")
        lines.append(f"  - 🟡 中危: {medium} 个")
        lines.append(f"  - 🟢 低危: {low} 个")
        lines.append(f"- **外部工具检测**: {external_count} 个")
        lines.append(f"- **动态检测（编译错误）**: {compile_errors} 个")
        lines.append(f"- **总计问题**: {len(static_defects) + external_count + compile_errors} 个\n")

        # 修复统计
        fixed_files = self.fix_result.get("fixed_files", [])
        total_fixed = self.fix_result.get("total_fixed", 0)
        lines.append(f"- **成功修复**: {total_fixed} 个问题")
        lines.append(f"- **修复文件数**: {len(fixed_files)} 个\n")

        # 验证结果
        verified = self.verify_result.get("verified_files", [])
        verify_errors = sum(1 for v in verified if v.get("compile_error"))
        lines.append(f"- **验证通过**: {len(verified) - verify_errors} 个文件")
        lines.append(f"- **验证失败**: {verify_errors} 个文件\n")

        # 2. 外部工具详情
        if external_data:
            lines.append("## 🔧 外部工具执行情况\n")
            lines.append("| 工具 | 检测数量 | 状态 |")
            lines.append("|------|---------|------|")
            for tool in ["ruff", "pylint", "mypy", "bandit"]:
                data = external_data.get(tool, {})
                if isinstance(data, dict):
                    count = data.get("count", 0)
                    if "error" in data:
                        status = f"❌ 错误: {data['error'][:50]}"
                    elif "stderr" in data and "No module named" in data["stderr"]:
                        status = "⚠️ 未安装"
                    else:
                        status = "✅ 正常"
                    lines.append(f"| {tool} | {count} | {status} |")
            lines.append("")

            # 3. 缺陷详情（带修复方案）
            lines.append("## 🐛 缺陷详情与修复方案\n")

            for severity in ["HIGH", "MEDIUM", "LOW"]:
                severity_defects = [d for d in static_defects if d.get("severity") == severity]
                if not severity_defects:
                    continue

                icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}[severity]
                lines.append(f"### {icon} {severity} 级别 ({len(severity_defects)} 个)\n")

                # 按文件分组
                by_file: Dict[str, List] = {}
                for d in severity_defects:
                    file = d.get("file", "unknown")
                    by_file.setdefault(file, []).append(d)

                for file, file_defects in sorted(by_file.items()):
                    lines.append(f"#### 📄 `{file}`\n")

                    for i, d in enumerate(file_defects, 1):
                        rule_id = d.get("rule_id", "")
                        line_no = d.get("line", 0)
                        msg = d.get("message", "")
                        snippet = d.get("snippet", "").strip()

                        lines.append(f"**{i}. [{rule_id}] 第 {line_no} 行**")
                        lines.append(f"- **问题**: {msg}")
                        if snippet:
                            lines.append(f"- **原代码**:")
                            lines.append(f"  ```python")
                            lines.append(f"  {snippet}")
                            lines.append(f"  ```")

                        # 添加修复方案
                        fix_suggestion = self._get_fix_suggestion(rule_id, snippet, msg)
                        if fix_suggestion:
                            lines.append(f"- **修复方案**:")
                            lines.append(f"  ```python")
                            lines.append(f"  {fix_suggestion}")
                            lines.append(f"  ```")

                        lines.append("")

            # ... 后面的代码保持不变 ...

            report = "\n".join(lines)

            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(report)

            return report

        def _get_fix_suggestion(self, rule_id: str, snippet: str, message: str) -> str:
            """根据规则ID生成修复建议"""

            # AST001: 可变默认参数
            if rule_id == "AST001":
                if "tags: List[str] = []" in snippet:
                    return "tags: List[str] = field(default_factory=list)  # 使用 field(default_factory=list)"
                elif "= []" in snippet:
                    return snippet.replace("= []", "= None  # 在 __post_init__ 中初始化为 []")
                elif "= {}" in snippet:
                    return snippet.replace("= {}", "= None  # 在 __post_init__ 中初始化为 {}")

            # AST002: is 比较
            elif rule_id == "AST002":
                if " is " in snippet:
                    return snippet.replace(" is ", " == ")
                elif " is not " in snippet:
                    return snippet.replace(" is not ", " != ")

            # AST003: 函数调用作为默认值
            elif rule_id == "AST003":
                if "datetime.now()" in snippet:
                    return snippet.replace("datetime.now()", "None  # 在 __post_init__ 中设置")

            # PY100: 未定义名称（这个通常是真实bug）
            elif rule_id == "PY100":
                if "colour" in message:
                    return "# 定义 colour 函数或导入: from termcolor import colored as colour"

            # PY202: max() 空序列
            elif rule_id == "PY202":
                if "max(" in snippet:
                    return snippet.replace("max(", "max(").replace(")", ", default=0)")

            # PY203: list.remove 错误
            elif rule_id == "PY203":
                if ".remove(" in snippet and "task_id" in snippet:
                    return "tasks.remove(task)  # 传入对象而非 ID"

            # PY051: 覆盖内建名
            elif rule_id == "PY051" or "PL-redefined-builtin" in rule_id:
                if "list =" in snippet:
                    return snippet.replace("list =", "task_list =")

            # RUFF-W292: 文件末尾缺少换行
            elif rule_id == "RUFF-W292":
                return "# 在文件末尾添加一个空行"

            # RUFF-I001: import 排序
            elif rule_id == "RUFF-I001":
                return "# 使用 'ruff check --fixers' 或 'isort' 自动排序导入"

            # PL-unexpected-keyword-arg: 参数名错误
            elif "unexpected-keyword-arg" in rule_id.lower():
                if "filter_tag=" in snippet:
                    return snippet.replace("filter_tag=", "filter_by_tag=")

            # PL-assignment-from-no-return: 赋值无返回值函数
            elif "assignment-from-no-return" in rule_id.lower():
                return "# 移除赋值语句，直接调用函数"

            # PL-unspecified-encoding: 缺少 encoding
            elif "unspecified-encoding" in rule_id.lower():
                if 'open(' in snippet and 'encoding' not in snippet:
                    return snippet.replace('open(', 'open(').replace(')', ', encoding="utf-8")')

            return ""

        # 4. 动态检测错误
        if compile_errors > 0:
            lines.append("## ⚠️ 动态检测（编译错误）\n")
            for err in dynamic_data.get("py_compile", [])[:10]:
                file = err.get("file", "unknown")
                error = err.get("error", "")[:200]
                lines.append(f"- **{file}**: {error}\n")

        # 5. 修复详情
        if fixed_files:
            lines.append("## ✅ 修复详情\n")
            for f in fixed_files[:20]:  # 最多显示20个文件
                file = f.get("file", "unknown")
                changes = f.get("changes", [])
                lines.append(f"### 📄 `{file}`\n")
                lines.append(f"- **修复规则数**: {len(changes)}")

                if changes:
                    lines.append("- **修复项**:")
                    for c in changes[:5]:  # 每个文件最多显示5个修复
                        rule = c.get("rule_id", "")
                        line_no = c.get("line", 0)
                        lines.append(f"  - 第 {line_no} 行: `{rule}`")
                lines.append("")

        # 6. 验证结果
        if verified:
            lines.append("## 🔍 验证结果\n")
            for v in verified[:20]:
                file = v.get("file", "unknown")
                if v.get("compile_error"):
                    lines.append(f"- ❌ **{file}**: 编译失败")
                    lines.append(f"  ```\n  {v.get('compile_error')[:200]}\n  ```")
                else:
                    lines.append(f"- ✅ **{file}**: 验证通过")
            lines.append("")

        # 7. 修复建议
        lines.append("## 💡 修复建议\n")
        if high > 0:
            lines.append("1. **优先修复高危问题**（安全漏洞、语法错误、未定义名称）")
        if compile_errors > 0:
            lines.append("2. **解决编译错误**（语法问题会阻止代码运行）")
        if medium > 0:
            lines.append("3. **处理中危问题**（逻辑错误、类型问题、可变默认参数）")
        if verify_errors > 0:
            lines.append("4. **人工 Review 验证失败的文件**（可能是误修复）")
        lines.append("5. **运行完整测试套件**确保修复未引入新问题")
        lines.append("6. **代码审查**确认修复符合项目规范\n")

        report = "\n".join(lines)

        # 保存到文件
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)

        return report

    def _get_fix_suggestion(self, rule_id: str, snippet: str, message: str) -> str:
        """根据规则ID生成修复建议"""

        # AST001: 可变默认参数
        if rule_id == "AST001":
            if "tags: List[str] = []" in snippet:
                return "tags: List[str] = field(default_factory=list)  # 使用 field(default_factory=list)"
            elif "= []" in snippet:
                return snippet.replace("= []", "= None  # 在 __post_init__ 中初始化为 []")
            elif "= {}" in snippet:
                return snippet.replace("= {}", "= None  # 在 __post_init__ 中初始化为 {}")

        # AST002: is 比较
        elif rule_id == "AST002":
            if " is " in snippet:
                return snippet.replace(" is ", " == ")
            elif " is not " in snippet:
                return snippet.replace(" is not ", " != ")

        # AST003: 函数调用作为默认值
        elif rule_id == "AST003":
            if "datetime.now()" in snippet:
                return snippet.replace("datetime.now()", "None  # 在 __post_init__ 中设置")

        # PY100: 未定义名称（这个通常是真实bug）
        elif rule_id == "PY100":
            if "colour" in message:
                return "# 定义 colour 函数或导入: from termcolor import colored as colour"

        # PY202: max() 空序列
        elif rule_id == "PY202":
            if "max(" in snippet:
                return snippet.replace("max(", "max(").replace(")", ", default=0)")

        # PY203: list.remove 错误
        elif rule_id == "PY203":
            if ".remove(" in snippet and "task_id" in snippet:
                return "tasks.remove(task)  # 传入对象而非 ID"

        # PY051: 覆盖内建名
        elif rule_id == "PY051" or "PL-redefined-builtin" in rule_id:
            if "list =" in snippet:
                return snippet.replace("list =", "task_list =")

        # RUFF-W292: 文件末尾缺少换行
        elif rule_id == "RUFF-W292":
            return "# 在文件末尾添加一个空行"

        # RUFF-I001: import 排序
        elif rule_id == "RUFF-I001":
            return "# 使用 'ruff check --fixers' 或 'isort' 自动排序导入"

        # PL-unexpected-keyword-arg: 参数名错误
        elif "unexpected-keyword-arg" in rule_id.lower():
            if "filter_tag=" in snippet:
                return snippet.replace("filter_tag=", "filter_by_tag=")

        # PL-assignment-from-no-return: 赋值无返回值函数
        elif "assignment-from-no-return" in rule_id.lower():
            return "# 移除赋值语句，直接调用函数"

        # PL-unspecified-encoding: 缺少 encoding
        elif "unspecified-encoding" in rule_id.lower():
            if 'open(' in snippet and 'encoding' not in snippet:
                return snippet.replace('open(', 'open(').replace(')', ', encoding="utf-8")')

        return ""
    def generate_html(self, output_path: str = None) -> str:
        """生成 HTML 报告"""
        static_defects = self.scan_result.get("static_builtin", [])
        dynamic_data = self.scan_result.get("dynamic", {})
        external_data = self.scan_result.get("external", {})

        high = sum(1 for d in static_defects if d.get("severity") == "HIGH")
        medium = sum(1 for d in static_defects if d.get("severity") == "MEDIUM")
        low = sum(1 for d in static_defects if d.get("severity") == "LOW")
        compile_errors = len(dynamic_data.get("py_compile", []))

        external_count = 0
        for tool in ["ruff", "pylint", "mypy", "bandit"]:
            tool_data = external_data.get(tool, {})
            if isinstance(tool_data, dict):
                external_count += tool_data.get("count", 0)

        total = len(static_defects) + external_count + compile_errors

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>代码缺陷检测报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; 
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                padding: 20px; min-height: 100vh; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; 
                      border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); 
                      overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   color: white; padding: 40px; }}
        .header h1 {{ font-size: 36px; margin-bottom: 10px; }}
        .header .timestamp {{ opacity: 0.9; font-size: 14px; }}
        .content {{ padding: 40px; }}
        h2 {{ color: #333; margin: 30px 0 20px; padding-bottom: 10px; 
              border-bottom: 2px solid #667eea; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
                    gap: 20px; margin: 30px 0; }}
        .summary-card {{ padding: 25px; border-radius: 12px; text-align: center; 
                        box-shadow: 0 4px 15px rgba(0,0,0,0.1); transition: transform 0.2s; }}
        .summary-card:hover {{ transform: translateY(-5px); }}
        .summary-card h3 {{ font-size: 42px; margin-bottom: 10px; }}
        .summary-card p {{ color: #666; font-size: 14px; }}
        .high {{ background: linear-gradient(135deg, #ff6b6b 0%, #ee5a6f 100%); color: white; }}
        .medium {{ background: linear-gradient(135deg, #feca57 0%, #ff9ff3 100%); color: white; }}
        .low {{ background: linear-gradient(135deg, #48dbfb 0%, #0abde3 100%); color: white; }}
        .total {{ background: linear-gradient(135deg, #5f27cd 0%, #341f97 100%); color: white; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; 
                 box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f8f9fa; font-weight: 600; color: #495057; }}
        tbody tr:hover {{ background: #f8f9fa; }}
        .defect {{ margin: 20px 0; padding: 20px; background: #f8f9fa; 
                   border-left: 4px solid #667eea; border-radius: 8px; }}
        .defect-header {{ font-weight: 600; margin-bottom: 10px; color: #495057; }}
        code {{ background: #e9ecef; padding: 3px 8px; border-radius: 4px; 
                font-family: 'Courier New', monospace; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; 
                 font-size: 12px; font-weight: 600; }}
        .badge-high {{ background: #ff6b6b; color: white; }}
        .badge-medium {{ background: #feca57; color: #333; }}
        .badge-low {{ background: #48dbfb; color: white; }}
        .footer {{ background: #f8f9fa; padding: 30px; text-align: center; 
                   color: #6c757d; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 代码缺陷检测报告</h1>
            <p class="timestamp">生成时间: {self.timestamp}</p>
        </div>

        <div class="content">
            <h2>📊 执行摘要</h2>
            <div class="summary">
                <div class="summary-card high">
                    <h3>{high}</h3>
                    <p>高危缺陷</p>
                </div>
                <div class="summary-card medium">
                    <h3>{medium}</h3>
                    <p>中危缺陷</p>
                </div>
                <div class="summary-card low">
                    <h3>{low}</h3>
                    <p>低危缺陷</p>
                </div>
                <div class="summary-card total">
                    <h3>{total}</h3>
                    <p>总计问题</p>
                </div>
            </div>

            <h2>📈 检测统计</h2>
            <table>
                <tr>
                    <th>检测类型</th>
                    <th>问题数量</th>
                    <th>占比</th>
                </tr>
                <tr>
                    <td>静态分析（内置规则）</td>
                    <td>{len(static_defects)}</td>
                    <td>{len(static_defects) / max(total, 1) * 100:.1f}%</td>
                </tr>
                <tr>
                    <td>外部工具（ruff/pylint/mypy/bandit）</td>
                    <td>{external_count}</td>
                    <td>{external_count / max(total, 1) * 100:.1f}%</td>
                </tr>
                <tr>
                    <td>动态检测（编译错误）</td>
                    <td>{compile_errors}</td>
                    <td>{compile_errors / max(total, 1) * 100:.1f}%</td>
                </tr>
            </table>

            <h2>🐛 缺陷列表（前 50 个）</h2>
            <table>
                <tr>
                    <th>严重性</th>
                    <th>文件</th>
                    <th>行号</th>
                    <th>规则</th>
                    <th>描述</th>
                </tr>
"""

        sorted_defects = sorted(static_defects,
                                key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x.get("severity"), 9))

        for d in sorted_defects[:50]:
            severity = d.get("severity", "LOW")
            file = d.get("file", "unknown")
            line = d.get("line", 0)
            rule = d.get("rule_id", "")
            msg = d.get("message", "")[:150]

            badge_class = f"badge-{severity.lower()}"
            html += f"""
            <tr>
                <td><span class="badge {badge_class}">{severity}</span></td>
                <td>{file}</td>
                <td>{line}</td>
                <td><code>{rule}</code></td>
                <td>{msg}</td>
            </tr>
"""

        html += f"""
            </table>

            <h2>💡 修复建议</h2>
            <ol style="line-height: 2; color: #495057;">
                <li>优先修复 <strong>{high}</strong> 个高危问题（安全漏洞、语法错误）</li>
                <li>处理 <strong>{medium}</strong> 个中危问题（逻辑错误、类型问题）</li>
                <li>解决 <strong>{compile_errors}</strong> 个编译错误</li>
                <li>运行完整测试确保修复未引入新问题</li>
            </ol>
        </div>

        <div class="footer">
            <p>报告由 Multi-Agent 代码修复系统自动生成</p>
        </div>
    </div>
</body>
</html>
"""

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)

        return html

    def generate_json(self, output_path: str = None) -> str:
        """生成 JSON 报告"""
        static_defects = self.scan_result.get("static_builtin", [])
        dynamic_data = self.scan_result.get("dynamic", {})
        external_data = self.scan_result.get("external", {})

        report = {
            "timestamp": self.timestamp,
            "summary": {
                "static_analysis": {
                    "total": len(static_defects),
                    "high": sum(1 for d in static_defects if d.get("severity") == "HIGH"),
                    "medium": sum(1 for d in static_defects if d.get("severity") == "MEDIUM"),
                    "low": sum(1 for d in static_defects if d.get("severity") == "LOW"),
                },
                "external_tools": {
                    tool: external_data.get(tool, {}).get("count", 0)
                    for tool in ["ruff", "pylint", "mypy", "bandit"]
                },
                "dynamic_analysis": {
                    "compile_errors": len(dynamic_data.get("py_compile", []))
                },
                "fixes": {
                    "total_fixed": self.fix_result.get("total_fixed", 0),
                    "fixed_files": len(self.fix_result.get("fixed_files", [])),
                },
                "verification": {
                    "verified_files": len(self.verify_result.get("verified_files", [])),
                    "compile_errors": sum(1 for v in self.verify_result.get("verified_files", [])
                                          if v.get("compile_error"))
                }
            },
            "defects": static_defects,
            "external_tools_details": external_data,
            "dynamic_errors": dynamic_data.get("py_compile", []),
            "fixes": self.fix_result.get("fixed_files", []),
            "verification": self.verify_result.get("verified_files", [])
        }

        json_str = json.dumps(report, ensure_ascii=False, indent=2)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)

        return json_str