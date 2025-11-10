# agents/verifier_agent.py
"""
VerifierAgent - 多语言代码验证Agent
"""
import sys
import os
from typing import Dict, Any, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_agent import BaseAgent
from utils.language_detector import Language, LanguageDetector
from verifiers.verifier_factory import VerifierFactory
from analyzers.scanner_factory import ScannerFactory


class VerifierAgent(BaseAgent):
    """多语言代码验证Agent"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("VerifierAgent", config or {})
        self.verifiers = {}

    def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """感知阶段：接收修复结果"""
        fix_results = input_data.get("fix_results", {})
        original_files = input_data.get("original_files", [])
        original_analysis = input_data.get("original_analysis", {})

        fixed_files = fix_results.get("fixed_files", [])

        self.log(f"📊 收到修复结果：{len(fixed_files)} 个文件待验证")

        return {
            "fix_results": fix_results,
            "fixed_files": fixed_files,
            "original_files": original_files,
            "original_analysis": original_analysis,
            "test_cases": input_data.get("test_cases", [])
        }

    def decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """决策阶段：确定验证策略"""
        fixed_files = perception.get("fixed_files", [])
        original_files = perception.get("original_files", [])
        original_analysis = perception.get("original_analysis", {})
        test_cases = perception.get("test_cases", [])

        strategy = {
            "verification_plans": [],
            "enable_syntax_check": True,
            "enable_rescan": True,
            "enable_tests": bool(test_cases),
            # ✅ 关键：传递原始数据
            "original_files": original_files,
            "original_analysis": original_analysis,
            "test_cases": test_cases
        }

        # 按语言分组
        files_by_language = {}
        for file in fixed_files:
            lang = file.get("language", "unknown")
            if lang not in files_by_language:
                files_by_language[lang] = []
            files_by_language[lang].append(file)

        # 为每种语言制定验证计划
        for lang_name, files in files_by_language.items():
            strategy["verification_plans"].append({
                "language": lang_name,
                "files": files,
                "file_count": len(files)
            })

        self.log(f"\n决策：制定了 {len(strategy['verification_plans'])} 个验证计划")
        self.log(f"   - 语法检查: {'启用' if strategy['enable_syntax_check'] else '禁用'}")
        self.log(f"   - 重新扫描: {'启用' if strategy['enable_rescan'] else '禁用'}")
        self.log(f"   - 功能测试: {'启用' if strategy['enable_tests'] else '禁用'}")

        return strategy

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """执行阶段：对每种语言执行验证"""
        verification_plans = decision.get("verification_plans", [])
        original_files = decision.get("original_files", [])
        original_analysis = decision.get("original_analysis", {})
        test_cases = decision.get("test_cases", [])

        all_results = {
            "by_language": {},
            "summary": {
                "total_files": 0,
                "compile_success": 0,
                "compile_failed": 0,
                "test_passed": 0,
                "test_failed": 0,
                "avg_fix_rate": 0.0,
                # ✅ 新增统计字段
                "total_original_issues": 0,
                "total_fixed_issues": 0,
                "total_remaining_issues": 0,
                "total_new_issues": 0
            },
            "verified_files": []
        }

        # 创建原始文件映射
        original_file_map = {f.get("file"): f for f in original_files}

        # 🔥 调试：输出原始文件映射
        print(f"\n[VerifierAgent] 原始文件映射: {len(original_file_map)} 个文件")
        if original_file_map:
            print(f"[VerifierAgent] 文件列表: {list(original_file_map.keys())}")

        # 对每种语言执行验证
        for plan in verification_plans:
            lang_name = plan["language"]
            files = plan["files"]

            self.log(f"\n{'=' * 60}")
            self.log(f"✅ 开始验证 {lang_name.upper()} 代码...")
            self.log(f"   待验证文件数: {len(files)}")

            try:
                # 获取语言枚举
                lang = Language.from_string(lang_name)

                # 创建验证器和扫描器
                verifier = VerifierFactory.create_verifier(lang)
                scanner = ScannerFactory.create_scanner([], lang)

                lang_results = {
                    "language": lang_name,
                    "files": [],
                    "summary": {
                        "total": len(files),
                        "compile_success": 0,
                        "compile_failed": 0,
                        "test_passed": 0,
                        "test_failed": 0,
                        # ✅ 新增统计字段
                        "total_original_issues": 0,
                        "total_fixed_issues": 0,
                        "total_remaining_issues": 0,
                        "total_new_issues": 0
                    }
                }

                # 验证每个文件
                total_fix_rate = 0.0
                verified_count = 0

                for fixed_file in files:
                    filename = fixed_file.get("file")

                    self.log(f"\n   📄 验证文件: {filename}")

                    # 获取原始文件
                    original_file = original_file_map.get(filename)
                    if not original_file:
                        self.log(f"      ⚠️ 未找到原始文件，跳过")
                        # 🔥 调试：查看为什么找不到
                        print(f"[VerifierAgent] 未找到原始文件: {filename}")
                        print(f"[VerifierAgent] 可用文件: {list(original_file_map.keys())[:3]}")
                        continue

                    # ✅ 从多个来源获取原始问题
                    original_issues = []
                    original_count = 0

                    # 优先级1：从 fixed_file 中获取
                    if "original_issues" in fixed_file:
                        original_issues = fixed_file.get("original_issues", [])
                        if not isinstance(original_issues, list):
                            original_issues = [original_issues]
                        original_count = len(original_issues)
                        print(f"[VerifierAgent] 从 fixed_file.original_issues 获取: {original_count} 个问题")

                    # 优先级2：从 fixed_file.original_issues_count 获取
                    if original_count == 0 and "original_issues_count" in fixed_file:
                        original_count = fixed_file.get("original_issues_count", 0)
                        if original_count > 0:
                            # 创建虚拟问题列表
                            original_issues = [{"index": i + 1} for i in range(original_count)]
                            print(f"[VerifierAgent] 从 fixed_file.original_issues_count 获取: {original_count} 个问题")

                    # 优先级3：从 original_analysis 中获取
                    if original_count == 0:
                        lang_analysis = original_analysis.get("by_language", {}).get(lang_name, {})
                        if isinstance(lang_analysis, dict):
                            issues_by_file = lang_analysis.get("issues_by_file", {})
                            if filename in issues_by_file:
                                original_issues = issues_by_file[filename]
                                if not isinstance(original_issues, list):
                                    original_issues = [original_issues]
                                original_count = len(original_issues)
                                print(f"[VerifierAgent] 从 original_analysis 获取: {original_count} 个问题")

                    # 优先级4：使用 fixed_count
                    if original_count == 0:
                        fixed_count = fixed_file.get("fixed_count", 0)
                        if fixed_count > 0:
                            original_count = fixed_count
                            original_issues = [{"index": i + 1} for i in range(fixed_count)]
                            print(f"[VerifierAgent] 从 fixed_file.fixed_count 推断: {fixed_count} 个问题")

                    # ✅ 最终检查
                    if original_count == 0:
                        print(f"[VerifierAgent] 警告：{filename} 无法获取原始问题，修复率可能不准确")

                    try:
                        # 执行验证
                        verify_result = verifier.verify(
                            original_file=original_file,
                            fixed_file=fixed_file,
                            original_issues=original_issues,
                            test_cases=test_cases,
                            scanner=scanner
                        )

                        # ✅ 计算统计数据
                        remaining_count = len(verify_result.remaining_issues)
                        fixed_count = max(0, original_count - remaining_count)
                        new_count = len(verify_result.new_issues)

                        # 统计编译结果
                        if verify_result.compile_success:
                            lang_results["summary"]["compile_success"] += 1
                            all_results["summary"]["compile_success"] += 1
                            self.log(f"[VerifierAgent]       ✅ 编译成功")
                        else:
                            lang_results["summary"]["compile_failed"] += 1
                            all_results["summary"]["compile_failed"] += 1
                            error_msg = verify_result.error_message or "未知错误"
                            self.log(f"[VerifierAgent]       ❌ 编译失败: {error_msg}")

                        # 统计测试结果
                        if verify_result.test_success:
                            lang_results["summary"]["test_passed"] += 1
                            all_results["summary"]["test_passed"] += 1
                            self.log(f"[VerifierAgent]       ✅ 测试通过")
                        else:
                            if test_cases:
                                lang_results["summary"]["test_failed"] += 1
                                all_results["summary"]["test_failed"] += 1
                                self.log(f"[VerifierAgent]       ⚠️ 测试失败")

                        # ✅ 显示详细的修复信息
                        self.log(f"[VerifierAgent]       原始问题: {original_count} 个")
                        self.log(f"[VerifierAgent]       修复问题: {fixed_count} 个")
                        self.log(f"[VerifierAgent]       剩余问题: {remaining_count} 个")
                        self.log(f"[VerifierAgent]       修复率: {verify_result.fix_rate:.1f}%")

                        # ✅ 显示新增问题（LLM引入）
                        if new_count > 0:
                            self.log(f"[VerifierAgent]       ⚠️ 新增问题: {new_count} 个（LLM引入）")
                            # 显示前3个新增问题的详情
                            for i, issue in enumerate(verify_result.new_issues[:3], 1):
                                rule_id = issue.get('rule_id', 'UNKNOWN')
                                line = issue.get('line', '?')
                                message = issue.get('message', '')
                                self.log(f"[VerifierAgent]          {i}. [{rule_id}] 第{line}行: {message}")
                            if new_count > 3:
                                self.log(f"[VerifierAgent]          ... 还有 {new_count - 3} 个")

                        # ✅ 累计统计
                        lang_results["summary"]["total_original_issues"] += original_count
                        lang_results["summary"]["total_fixed_issues"] += fixed_count
                        lang_results["summary"]["total_remaining_issues"] += remaining_count
                        lang_results["summary"]["total_new_issues"] += new_count

                        all_results["summary"]["total_original_issues"] += original_count
                        all_results["summary"]["total_fixed_issues"] += fixed_count
                        all_results["summary"]["total_remaining_issues"] += remaining_count
                        all_results["summary"]["total_new_issues"] += new_count

                        total_fix_rate += verify_result.fix_rate
                        verified_count += 1

                        # 保存验证结果
                        verified_file = {
                            "file": filename,
                            "language": lang_name,
                            "content": fixed_file.get("content"),
                            "verification": verify_result.to_dict(),
                            "original_issues_count": original_count,
                            "fixed_issues_count": fixed_count,
                            "remaining_issues_count": remaining_count,
                            "new_issues_count": new_count,
                            "fix_rate": verify_result.fix_rate
                        }

                        all_results["verified_files"].append(verified_file)
                        lang_results["files"].append(verify_result.to_dict())

                    except Exception as e:
                        self.log(f"[VerifierAgent]       ❌ 验证异常: {str(e)}")
                        import traceback
                        error_trace = traceback.format_exc()
                        print(f"[VerifierAgent] 验证异常详情:\n{error_trace}")

                # ✅ 计算平均修复率
                if verified_count > 0:
                    lang_results["avg_fix_rate"] = total_fix_rate / verified_count
                else:
                    lang_results["avg_fix_rate"] = 0.0

                all_results["by_language"][lang_name] = lang_results
                all_results["summary"]["total_files"] += len(files)

                # ✅ 输出语言级别的汇总
                self.log(f"\n   ✅ {lang_name.upper()} 验证完成:")
                self.log(f"[VerifierAgent]       - 编译成功: {lang_results['summary']['compile_success']} 个")
                self.log(f"[VerifierAgent]       - 编译失败: {lang_results['summary']['compile_failed']} 个")

                # 计算并显示修复率
                total_orig = lang_results["summary"]["total_original_issues"]
                total_fixed = lang_results["summary"]["total_fixed_issues"]
                if total_orig > 0:
                    actual_fix_rate = (total_fixed / total_orig) * 100
                    self.log(f"[VerifierAgent]       - 平均修复率: {actual_fix_rate:.1f}%")
                    self.log(f"[VerifierAgent]       - 总修复: {total_fixed}/{total_orig} 个问题")
                else:
                    self.log(f"[VerifierAgent]       - 平均修复率: {lang_results.get('avg_fix_rate', 0):.1f}%")

                # 显示新增问题统计
                total_new = lang_results["summary"]["total_new_issues"]
                if total_new > 0:
                    self.log(f"[VerifierAgent]       - ⚠️ 新增问题: {total_new} 个（LLM引入）")

            except Exception as e:
                self.log(f"   ❌ {lang_name.upper()} 验证失败: {str(e)}")
                import traceback
                traceback.print_exc()

        # ✅ 计算总体平均修复率（基于实际修复数）
        if all_results["summary"]["total_original_issues"] > 0:
            all_results["summary"]["avg_fix_rate"] = (
                                                             all_results["summary"]["total_fixed_issues"] /
                                                             all_results["summary"]["total_original_issues"]
                                                     ) * 100
        elif all_results["summary"]["total_files"] > 0 and all_results["by_language"]:
            # 降级方案：使用各语言平均值
            total_rate = sum(
                lang_res.get("avg_fix_rate", 0)
                for lang_res in all_results["by_language"].values()
            )
            all_results["summary"]["avg_fix_rate"] = total_rate / len(all_results["by_language"])

        # ✅ 输出总体统计
        self.log(f"\n{'=' * 60}")
        self.log(f"📊 总体验证统计：")
        self.log(f"   - 验证文件: {all_results['summary']['total_files']} 个")
        self.log(f"   - 编译成功: {all_results['summary']['compile_success']} 个")
        self.log(f"   - 编译失败: {all_results['summary']['compile_failed']} 个")

        # 显示问题修复统计
        total_orig = all_results["summary"]["total_original_issues"]
        total_fixed = all_results["summary"]["total_fixed_issues"]
        total_remaining = all_results["summary"]["total_remaining_issues"]
        total_new = all_results["summary"]["total_new_issues"]

        if total_orig > 0:
            self.log(f"   - 原始问题: {total_orig} 个")
            self.log(f"   - 修复问题: {total_fixed} 个")
            self.log(f"   - 剩余问题: {total_remaining} 个")
            self.log(f"   - 平均修复率: {all_results['summary']['avg_fix_rate']:.1f}%")
        else:
            self.log(f"   - 平均修复率: {all_results['summary']['avg_fix_rate']:.1f}%")

        if total_new > 0:
            self.log(f"   - ⚠️ 新增问题: {total_new} 个（LLM引入）")

        return all_results