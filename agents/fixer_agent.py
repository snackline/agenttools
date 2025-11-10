# agents/fixer_agent.py
"""
FixerAgent - 多语言代码修复Agent
"""
import sys
import os
from typing import Dict, Any, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_agent import BaseAgent
from utils.language_detector import Language, LanguageDetector
from fixers.fixer_factory import FixerFactory


class FixerAgent(BaseAgent):
    """多语言代码修复Agent"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("FixerAgent", config or {})
        self.llm_client = config.get("llm_client") if config else None
        self.fixers = {}

    def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """感知阶段：接收分析结果"""
        analysis = input_data.get("analysis", {})
        files = input_data.get("files", [])
        user_request = input_data.get("user_request", "")

        by_language = analysis.get("by_language", {})

        self.log(f"📊 收到分析结果：涉及 {len(by_language)} 种语言")
        for lang, lang_analysis in by_language.items():
            # ✅ 安全地获取 total
            total = lang_analysis.get("total", 0) if isinstance(lang_analysis, dict) else 0
            self.log(f"   - {lang.upper()}: {total} 个问题待修复")

        # ✅ 检查 LLM 配置
        use_llm = self.config.get("use_llm", True) and self.llm_client is not None

        # 🔥 调试：输出 LLM 配置
        print(f"\n🔥🔥🔥 [DEBUG] config.use_llm: {self.config.get('use_llm', True)}")
        print(f"🔥🔥🔥 [DEBUG] llm_client 是否存在: {self.llm_client is not None}")
        print(f"🔥🔥🔥 [DEBUG] 最终 use_llm: {use_llm}")

        if self.llm_client:
            print(f"🔥🔥🔥 [DEBUG] llm_client 类型: {type(self.llm_client)}")
        else:
            print(f"🔥🔥🔥 [DEBUG] llm_client 为 None!")

        return {
            "analysis": analysis,
            "files": files,
            "by_language": by_language,
            "user_request": user_request,
            "use_rules": self.config.get("use_rules", True),
            "use_llm": use_llm
        }

    def decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """决策阶段：确定修复策略"""
        by_language = perception.get("by_language", {})
        use_rules = perception.get("use_rules", True)
        use_llm = perception.get("use_llm", False)

        strategy = {
            "repair_plans": [],
            "use_rules": use_rules,
            "use_llm": use_llm
        }

        # 为每种语言制定修复计划
        for lang_name, lang_analysis in by_language.items():
            if not isinstance(lang_analysis, dict):
                continue

            issues_by_file = lang_analysis.get("issues_by_file", {})

            if not issues_by_file:
                continue

            repair_plan = {
                "language": lang_name,
                "files_to_fix": [],
                "total_issues": lang_analysis.get("total", 0)
            }

            for filename, issues in issues_by_file.items():
                # ✅ 确保 issues 是列表
                if not isinstance(issues, list):
                    issues = [issues]

                repair_plan["files_to_fix"].append({
                    "filename": filename,
                    "issues": issues,
                    "issue_count": len(issues)
                })

            strategy["repair_plans"].append(repair_plan)

        self.log(f"\n决策：制定了 {len(strategy['repair_plans'])} 个修复计划")
        self.log(f"   - 使用规则修复: {'是' if use_rules else '否'}")
        self.log(f"   - 使用LLM修复: {'是' if use_llm else '否'}")

        return strategy

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """执行阶段：对每种语言执行修复"""
        repair_plans = decision.get("repair_plans", [])
        use_rules = decision.get("use_rules", True)
        use_llm = decision.get("use_llm", False)
        user_request = decision.get("user_request", "")

        all_results = {
            "by_language": {},
            "fixed_files": [],
            "summary": {
                "total_files": 0,
                "successfully_fixed": 0,
                "failed": 0,
                "total_fixes": 0
            }
        }

        # 获取原始文件映射
        files = decision.get("files", [])
        file_map = {f.get("file"): f for f in files}

        # 🔥 调试：检查文件映射
        print(f"\n🔥🔥🔥 [DEBUG] file_map keys 数量: {len(file_map)}")
        if len(file_map) > 0:
            print(f"🔥🔥🔥 [DEBUG] file_map 前3个键: {list(file_map.keys())[:3]}")

        # 对每种语言执行修复
        for plan in repair_plans:
            lang_name = plan["language"]
            files_to_fix = plan["files_to_fix"]

            self.log(f"\n{'=' * 60}")
            self.log(f"🔧 开始修复 {lang_name.upper()} 代码...")
            self.log(f"   待修复文件数: {len(files_to_fix)}")

            try:
                # 获取语言枚举
                lang = Language.from_string(lang_name)

                # 创建修复器
                fixer = FixerFactory.create_fixer(lang, self.llm_client)

                lang_results = {
                    "language": lang_name,
                    "files": [],
                    "summary": {
                        "total": len(files_to_fix),
                        "success": 0,
                        "failed": 0
                    }
                }

                # 修复每个文件
                for file_info in files_to_fix:
                    filename = file_info["filename"]
                    issues = file_info["issues"]

                    self.log(f"\n   📄 修复文件: {filename}")
                    self.log(f"      问题数: {len(issues)}")

                    # 🔥 调试：查看 issues 的内容
                    print(f"\n🔥🔥🔥 [DEBUG] filename: {filename}")
                    print(f"🔥🔥🔥 [DEBUG] issues 类型: {type(issues)}")
                    print(f"🔥🔥🔥 [DEBUG] issues 数量: {len(issues)}")
                    if issues and len(issues) > 0:
                        print(f"🔥🔥🔥 [DEBUG] 第一个 issue 类型: {type(issues[0])}")
                        print(f"🔥🔥🔥 [DEBUG] 第一个 issue 内容: {str(issues[0])[:200]}")

                    # 获取原始文件内容
                    original_file = file_map.get(filename)

                    # 🔥 调试：检查是否找到文件
                    print(f"🔥🔥🔥 [DEBUG] original_file 是否找到: {original_file is not None}")

                    if not original_file:
                        self.log(f"      ⚠️ 未找到原始文件，跳过")
                        lang_results["summary"]["failed"] += 1

                        # ✅ 即使未找到文件，也记录到 fixed_files（标记为错误）
                        all_results["fixed_files"].append({
                            "file": filename,
                            "content": "",
                            "language": lang_name,
                            "original_content": "",
                            "fixed_count": 0,
                            "method": "none",
                            "status": "error",
                            "success": False,
                            "error_message": "未找到原始文件"
                        })
                        continue

                    try:
                        # 🔥 调试：调用修复前
                        print(f"🔥🔥🔥 [DEBUG] 开始调用 fixer.fix()")
                        print(f"🔥🔥🔥 [DEBUG] use_rules={use_rules}, use_llm={use_llm}")

                        # 执行修复
                        fix_result = fixer.fix(
                            original_file,
                            issues,
                            use_rules=use_rules,
                            use_llm=use_llm,
                            user_request=user_request
                        )

                        # 🔥 调试：修复结果
                        print(f"🔥🔥🔥 [DEBUG] fix_result.success: {fix_result.success}")
                        print(f"🔥🔥🔥 [DEBUG] fix_result.error_message: {fix_result.error_message}")
                        print(f"🔥🔥🔥 [DEBUG] fix_result.method: {fix_result.method}")
                        print(f"🔥🔥🔥 [DEBUG] fix_result.fixed_count: {fix_result.fixed_count}")

                        # agents/fixer_agent.py - execute() 方法中

                        # ✅ 构建输出文件（包含原始问题）
                        fixed_file = {
                            "file": filename,
                            "content": fix_result.fixed_content if fix_result.success else original_file.get("content"),
                            "language": lang_name,
                            "original_content": original_file.get("content"),
                            "fixed_count": fix_result.fixed_count,
                            "method": fix_result.method,
                            "status": "fixed" if fix_result.success else "failed",
                            "success": fix_result.success,
                            "error_message": fix_result.error_message if not fix_result.success else "",
                            "original_issues": issues,  # ← 关键：保存原始问题
                            "original_issues_count": len(issues)  # ← 关键：保存问题数量
                        }

                        # ✅ 统一添加到 fixed_files（无论成功失败）
                        all_results["fixed_files"].append(fixed_file)
                        lang_results["files"].append(fix_result.to_dict())

                        # 更新统计和日志
                        if fix_result.success:
                            self.log(f"      ✅ 修复成功！")
                            self.log(f"         方法: {fix_result.method}")
                            self.log(f"         修复数量: {fix_result.fixed_count}")

                            lang_results["summary"]["success"] += 1
                            all_results["summary"]["successfully_fixed"] += 1
                            all_results["summary"]["total_fixes"] += fix_result.fixed_count
                        else:
                            self.log(f"      ⚠️ 未修复（保留原始代码）: {fix_result.error_message or '未知错误'}")
                            lang_results["summary"]["failed"] += 1
                            all_results["summary"]["failed"] += 1

                    except Exception as e:
                        self.log(f"      ❌ 修复异常: {str(e)}")
                        import traceback
                        error_trace = traceback.format_exc()
                        print(f"🔥🔥🔥 [DEBUG] 异常堆栈:\n{error_trace}")

                        lang_results["summary"]["failed"] += 1
                        all_results["summary"]["failed"] += 1

                        # ✅ 异常时也输出原始文件
                        fixed_file = {
                            "file": filename,
                            "content": original_file.get("content"),
                            "language": lang_name,
                            "original_content": original_file.get("content"),
                            "fixed_count": 0,
                            "method": "none",
                            "status": "error",
                            "success": False,
                            "error_message": str(e)
                        }
                        all_results["fixed_files"].append(fixed_file)

                all_results["by_language"][lang_name] = lang_results
                all_results["summary"]["total_files"] += len(files_to_fix)

                self.log(f"\n   ✅ {lang_name.upper()} 修复完成:")
                self.log(f"      - 成功: {lang_results['summary']['success']} 个文件")
                self.log(f"      - 失败: {lang_results['summary']['failed']} 个文件")

            except Exception as e:
                self.log(f"   ❌ {lang_name.upper()} 修复失败: {str(e)}")
                import traceback
                traceback.print_exc()

        self.log(f"\n{'=' * 60}")
        self.log(f"📊 总体修复统计：")
        self.log(f"   - 处理文件: {all_results['summary']['total_files']} 个")
        self.log(f"   - 成功修复: {all_results['summary']['successfully_fixed']} 个")
        self.log(f"   - 修复失败: {all_results['summary']['failed']} 个")
        self.log(f"   - 总修复数: {all_results['summary']['total_fixes']} 处")
        self.log(f"   - fixed_files 总数: {len(all_results['fixed_files'])} 个")  # ← 新增

        return all_results