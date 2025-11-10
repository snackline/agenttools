# agents/analyzer_agent.py
"""
AnalyzerAgent - 多语言代码分析Agent
"""
import sys
import os
from typing import Dict, Any, List
DEBUG_ANALYZER = os.environ.get("ANALYZER_DEBUG", "0") == "1"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_agent import BaseAgent
from utils.language_detector import Language, LanguageDetector


class AnalyzerAgent(BaseAgent):
    """多语言代码分析Agent"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("AnalyzerAgent", config or {})
        self.analysis_results = {}

    def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """感知阶段：接收扫描结果"""
        scan_results = input_data.get("scan_results", {})
        files = input_data.get("files", [])

        # 统计信息
        summary = scan_results.get("summary", {})
        total_defects = summary.get("total_defects", 0)
        by_language = summary.get("by_language", {})

        self.log(f"📊 收到扫描结果：总计 {total_defects} 个问题")

        if by_language:
            self.log(f"   按语言分布：")
            # ✅ 处理两种可能的数据格式
            for lang, stats in by_language.items():
                if isinstance(stats, dict):
                    # 字典格式：{"total": 100, ...}
                    count = stats.get('total', 0)
                elif isinstance(stats, int):
                    # 整数格式：100
                    count = stats
                else:
                    count = 0

                self.log(f"      • {lang.upper()}: {count} 个")

        return {
            "scan_results": scan_results,
            "files": files,
            "total_defects": total_defects,
            "by_language": scan_results.get("by_language", {})  # ✅ 使用完整数据
        }

    def decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """决策阶段：分析问题优先级和修复策略"""
        by_language = perception.get("by_language", {})

        # 如果没有问题，直接返回
        if not by_language or perception.get("total_defects", 0) == 0:
            self.log("\n✅ 未发现问题，无需分析")
            return {
                "fix_plans": [],
                "priority_order": [],
                "recommendations": []
            }

        strategy = {
            "fix_plans": [],
            "priority_order": [],
            "recommendations": []
        }

        # 为每种语言制定修复计划
        for lang_name, lang_results in by_language.items():
            # ✅ 处理可能的错误情况
            if "error" in lang_results:
                self.log(f"⚠️ {lang_name.upper()} 扫描失败，跳过分析")
                continue

            summary = lang_results.get("summary", {})

            if summary.get("total", 0) == 0:
                continue

            # 获取严重程度统计
            builtin = lang_results.get("builtin", [])
            external = lang_results.get("external", [])

            # ✅ 统计严重程度（处理字符串和字典）
            high_count = 0
            medium_count = 0
            low_count = 0

            for issue in builtin + external:
                if isinstance(issue, dict):
                    severity = issue.get("severity", "LOW")
                elif isinstance(issue, str):
                    # 从字符串判断严重程度
                    severity = "MEDIUM"
                    if any(kw in issue.lower() for kw in ["error", "critical", "fatal"]):
                        severity = "HIGH"
                    elif any(kw in issue.lower() for kw in ["warning", "info"]):
                        severity = "LOW"
                else:
                    severity = "LOW"

                if severity == "HIGH":
                    high_count += 1
                elif severity == "MEDIUM":
                    medium_count += 1
                else:
                    low_count += 1

            # 计算优先级得分
            priority_score = high_count * 10 + medium_count * 5 + low_count * 1

            fix_plan = {
                "language": lang_name,
                "total_issues": summary.get("total", 0),
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
                "priority_score": priority_score,
                "builtin_issues": builtin,
                "external_issues": external,
                "dynamic_results": lang_results.get("dynamic", {}),
            }

            strategy["fix_plans"].append(fix_plan)

        # 按优先级排序
        strategy["fix_plans"].sort(key=lambda x: x["priority_score"], reverse=True)
        strategy["priority_order"] = [plan["language"] for plan in strategy["fix_plans"]]

        # 生成建议
        for plan in strategy["fix_plans"]:
            lang = plan["language"]

            if plan["high"] > 0:
                strategy["recommendations"].append(
                    f"⚠️ {lang.upper()}: 发现 {plan['high']} 个高危问题，建议优先修复"
                )

            dynamic_results = plan["dynamic_results"]
            if isinstance(dynamic_results, dict) and not dynamic_results.get("compile_success", True):
                strategy["recommendations"].append(
                    f"❌ {lang.upper()}: 代码存在编译错误，需要先修复语法问题"
                )

        self.log(f"\n决策：制定了 {len(strategy['fix_plans'])} 个修复计划")
        if strategy['priority_order']:
            self.log(f"优先级顺序：")
            for i, lang in enumerate(strategy['priority_order'], 1):
                plan = next(p for p in strategy['fix_plans'] if p['language'] == lang)
                self.log(f"   {i}. {lang.upper()}: {plan['total_issues']} 个问题 "
                         f"(HIGH={plan['high']}, MEDIUM={plan['medium']}, LOW={plan['low']})")

        return strategy

    # agents/analyzer_agent.py

    def execute(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """执行阶段：生成详细的分析报告"""
        fix_plans = decision.get("fix_plans", [])
        recommendations = decision.get("recommendations", [])

        analysis_report = {
            "summary": {
                "total_languages": len(fix_plans),
                "total_issues": sum(plan["total_issues"] for plan in fix_plans),
                "high_priority": sum(plan["high"] for plan in fix_plans),
                "medium_priority": sum(plan["medium"] for plan in fix_plans),
                "low_priority": sum(plan["low"] for plan in fix_plans),
            },
            "by_language": {},
            "recommendations": recommendations,
            "fix_plans": fix_plans
        }

        # 按语言分组问题
        for plan in fix_plans:
            lang = plan["language"]

            # 合并内置和外部工具的问题
            all_issues = plan["builtin_issues"] + plan["external_issues"]

            # ✅ 按文件分组（增强文件名提取）
            issues_by_file = {}
            for issue in all_issues:
                # ✅ 处理字符串和字典两种格式
                if isinstance(issue, dict):
                    # 尝试多种文件名字段
                    raw_file = (
                            issue.get("file") or
                            issue.get("filename") or
                            issue.get("path") or
                            "unknown"
                    )

                    # ✅ 规范化文件名（去除路径）
                    if raw_file and raw_file != "unknown":
                        # 处理 Windows/Linux 路径
                        if "\\" in raw_file or "/" in raw_file:
                            file = os.path.basename(raw_file)
                            # 🔥 调试
                            if DEBUG_ANALYZER:
                                print(f"[AnalyzerAgent] 文件名规范化: {raw_file} -> {file}")
                        else:
                            file = raw_file
                    else:
                        file = "unknown"

                    if file not in issues_by_file:
                        issues_by_file[file] = []
                    issues_by_file[file].append(issue)

                elif isinstance(issue, str):
                    # 字符串类型，尝试从内容提取文件名
                    file = "unknown"
                    # 简单的文件名提取（格式：file.py:line: message）
                    if ":" in issue:
                        parts = issue.split(":")
                        if len(parts) > 0:
                            raw_file = parts[0].strip()
                            # ✅ 规范化
                            file = os.path.basename(raw_file) if raw_file else "unknown"

                    if file not in issues_by_file:
                        issues_by_file[file] = []

                    # 转换为字典格式
                    issues_by_file[file].append({
                        "type": "external_tool",
                        "severity": "MEDIUM",
                        "message": issue,
                        "file": file,
                        "language": lang
                    })

            # 🔥 调试：输出分组结果
            if DEBUG_ANALYZER:
                print(f"\n[AnalyzerAgent] {lang.upper()} 问题分组结果:")
                for fname, issues_list in issues_by_file.items():
                    print(f"  - {fname}: {len(issues_list)} 个问题")

            # 按严重程度分组
            issues_by_severity = {"HIGH": [], "MEDIUM": [], "LOW": []}

            for issue in all_issues:
                if isinstance(issue, dict):
                    severity = issue.get("severity", "LOW")
                    if severity in issues_by_severity:
                        issues_by_severity[severity].append(issue)
                elif isinstance(issue, str):
                    # 从字符串判断严重程度
                    severity = "MEDIUM"
                    if any(kw in issue.lower() for kw in ["error", "critical", "fatal"]):
                        severity = "HIGH"
                    elif any(kw in issue.lower() for kw in ["warning", "info"]):
                        severity = "LOW"

                    issue_dict = {
                        "type": "external_tool",
                        "severity": severity,
                        "message": issue,
                        "language": lang
                    }
                    issues_by_severity[severity].append(issue_dict)

            analysis_report["by_language"][lang] = {
                "total": plan["total_issues"],
                "issues_by_file": issues_by_file,
                "issues_by_severity": issues_by_severity,
                "dynamic_check": plan["dynamic_results"]
            }

        self.log("\n✅ 分析完成！")
        self.log(f"   - 涉及语言: {analysis_report['summary']['total_languages']} 种")
        self.log(f"   - 总问题数: {analysis_report['summary']['total_issues']} 个")
        self.log(f"   - 优先级分布: HIGH={analysis_report['summary']['high_priority']}, "
                 f"MEDIUM={analysis_report['summary']['medium_priority']}, "
                 f"LOW={analysis_report['summary']['low_priority']}")

        if recommendations:
            self.log("\n📌 建议：")
            for rec in recommendations:
                self.log(f"   {rec}")

        return analysis_report


# 兼容旧版本的analyze方法
def analyze_defects(defects: List[Dict], files: List[Dict]) -> Dict[str, Any]:
    """旧版本兼容接口"""
    agent = AnalyzerAgent()

    # 构造输入
    input_data = {
        "scan_results": {
            "defects": defects,
            "summary": {
                "total_defects": len(defects),
                "by_language": {}
            }
        },
        "files": files
    }

    perception = agent.perceive(input_data)
    decision = agent.decide(perception)
    result = agent.execute(decision)

    return result