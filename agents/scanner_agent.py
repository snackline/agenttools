# agents/scanner_agent.py
"""
ScannerAgent - 多语言代码扫描Agent
"""
import sys
import os
from typing import Dict, Any, List

# 添加路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_agent import BaseAgent
from utils.language_detector import Language, LanguageDetector
from analyzers.scanner_factory import ScannerFactory


class ScannerAgent(BaseAgent):
    """多语言代码扫描Agent"""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("ScannerAgent", config or {})
        self.scanners = {}
        self.language_stats = {}

    def perceive(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """感知阶段：按语言分类文件"""
        files = input_data.get("files", [])

        # 按语言分类文件
        classified_files = LanguageDetector.classify_files(files)

        # 统计并输出
        self.log("📊 文件语言分类统计：")
        for lang, file_list in classified_files.items():
            if file_list and lang != Language.UNKNOWN:
                lang_info = LanguageDetector.get_language_info(lang)
                self.log(f"   - {lang_info['name']}: {len(file_list)} 个文件")

        if classified_files[Language.UNKNOWN]:
            self.log(f"   - 未识别: {len(classified_files[Language.UNKNOWN])} 个文件")

        # 保存统计
        self.language_stats = {
            lang.value: len(file_list)
            for lang, file_list in classified_files.items()
            if file_list and lang != Language.UNKNOWN
        }

        return {
            "files": files,
            "classified_files": classified_files,
            "language_stats": self.language_stats,
            "enable_external": self.config.get("enable_external", True),
            "enable_dynamic": self.config.get("enable_dynamic", True),
            "timeout": self.config.get("timeout", 10)
        }

    def decide(self, perception: Dict[str, Any]) -> Dict[str, Any]:
        """决策阶段：确定扫描策略"""
        classified_files = perception.get("classified_files", {})

        strategy = {
            "scan_plans": [],
            "enable_external": perception.get("enable_external", True),
            "enable_dynamic": perception.get("enable_dynamic", True),
        }

        # 为每种语言制定扫描计划
        for lang, file_list in classified_files.items():
            if not file_list or lang == Language.UNKNOWN:
                continue

            lang_info = LanguageDetector.get_language_info(lang)

            strategy["scan_plans"].append({
                "language": lang,
                "language_name": lang_info["name"],
                "files": file_list,
                "file_count": len(file_list),
                "tools": lang_info.get("external_tools", []),
            })

        self.log(f"决策：将对 {len(strategy['scan_plans'])} 种语言进行扫描")

        return strategy

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行：扫描所有文件"""
        files = input_data.get("files", [])

        if not files:
            return {
                "success": False,
                "error": "没有文件需要扫描"
            }

        # 按语言分类
        classified_files = LanguageDetector.classify_files(files)

        # 统计
        total_scanned = 0
        all_results = {}

        # 对每种语言进行扫描
        for language, lang_files in classified_files.items():
            if not lang_files or language == Language.UNKNOWN:
                continue

            lang_info = LanguageDetector.get_language_info(language)
            lang_name = lang_info["name"].lower()

            self.log("")
            self.log("=" * 60)
            self.log(f"🔍 开始扫描 {language.value} 代码...")
            self.log(f"   文件数: {len(lang_files)}")

            try:
                # 创建扫描器
                scanner = ScannerFactory.create_scanner(lang_files, language)

                # 1. 内置规则扫描
                self.log(f"   执行内置规则扫描...")
                builtin_defects = scanner.scan()

                if not isinstance(builtin_defects, list):
                    self.log(f"   ⚠️ 警告：内置扫描返回类型错误，已转换为空列表")
                    builtin_defects = []

                self.log(f"   ✅ 内置规则扫描完成: {len(builtin_defects)} 个问题")

                # 2. 外部工具扫描
                external_defects = []
                if self.config.get("enable_external", False):
                    try:
                        self.log(f"   执行外部工具扫描...")
                        external_result = scanner.scan_with_external_tools(lang_files)

                        if isinstance(external_result, dict):
                            external_defects = external_result.get("defects", [])
                        elif isinstance(external_result, list):
                            external_defects = external_result
                        else:
                            external_defects = []

                        self.log(f"   ✅ 外部工具扫描完成: {len(external_defects)} 个问题")
                    except Exception as e:
                        self.log(f"   ⚠️ 外部工具扫描失败: {e}")
                        external_defects = []
                else:
                    self.log(f"   ℹ️ 外部工具扫描已禁用")

                # 3. 动态检测
                dynamic_result = {}
                if self.config.get("enable_dynamic", False):
                    try:
                        self.log(f"   执行编译检查...")
                        dynamic_result = scanner.check_compilation(lang_files)

                        if dynamic_result.get("compile_success", False):
                            self.log(f"   ✅ 编译检查通过")
                        else:
                            errors = dynamic_result.get("errors", [])
                            self.log(f"   ⚠️ 编译检查发现 {len(errors)} 个错误")
                    except Exception as e:
                        self.log(f"   ⚠️ 编译检查失败: {e}")
                else:
                    self.log(f"   ℹ️ 编译检查已禁用")

                # 合并所有缺陷
                all_defects = builtin_defects + external_defects

                # 保存结果
                all_results[lang_name] = {
                    "files": lang_files,
                    "builtin": builtin_defects,
                    "external": external_defects,
                    "dynamic": dynamic_result,
                    "summary": {
                        "total": len(all_defects),
                        "builtin_count": len(builtin_defects),
                        "external_count": len(external_defects)
                    }
                }

                total_scanned += len(lang_files)
                self.log(f"   ✅ {language.value} 扫描完成，共发现 {len(all_defects)} 个问题")

            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                self.log(f"   ❌ {language.value} 扫描失败: {e}")
                self.log(f"   错误详情:\n{error_trace}")

                all_results[lang_name] = {
                    "error": str(e),
                    "error_trace": error_trace,
                    "files": lang_files,
                    "builtin": [],
                    "external": [],
                    "dynamic": {},
                    "summary": {"total": 0}
                }

        # 生成总结
        summary = self._generate_summary(all_results)

        self.log("")
        self.log("=" * 60)
        self.log("📊 总体统计：")
        self.log(f"   - 扫描文件: {total_scanned} 个")
        self.log(f"   - 发现问题: {summary['total_defects']} 个")
        self.log(f"   - 严重程度分布:")
        for severity, count in summary["by_severity"].items():
            self.log(f"       • {severity}: {count} 个")

        return {
            "success": True,
            "by_language": all_results,
            "summary": summary,
            "total_scanned": total_scanned
        }

    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """生成扫描结果总结"""
        total_defects = 0
        by_severity = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        by_language = {}

        for lang_name, lang_result in results.items():
            if "error" in lang_result:
                continue

            builtin = lang_result.get("builtin", [])
            external = lang_result.get("external", [])
            all_defects = builtin + external

            total_defects += len(all_defects)
            by_language[lang_name] = len(all_defects)

            # 统计严重程度
            for defect in all_defects:
                # ✅ 增加类型检查
                if isinstance(defect, dict):
                    severity = defect.get("severity", "LOW")
                elif isinstance(defect, str):
                    # 如果是字符串，尝试从内容判断严重程度
                    severity = "MEDIUM"  # 默认中等
                    if any(keyword in defect.lower() for keyword in ["error", "critical", "fatal"]):
                        severity = "HIGH"
                    elif any(keyword in defect.lower() for keyword in ["warning", "info"]):
                        severity = "LOW"
                else:
                    # 未知类型，默认低危
                    severity = "LOW"

                if severity in by_severity:
                    by_severity[severity] += 1

        return {
            "total_defects": total_defects,
            "by_severity": by_severity,
            "by_language": by_language
        }