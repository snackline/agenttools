# verifiers/base_verifier.py
"""
BaseVerifier - 所有语言验证器的基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.common import VerificationResult
from utils.language_detector import Language


class BaseVerifier(ABC):
    """验证器基类"""

    def __init__(self, language: Language):
        """
        Args:
            language: 目标语言
        """
        self.language = language

    @abstractmethod
    def verify_syntax(self, file: Dict[str, Any]) -> Dict[str, Any]:
        """
        语法验证（编译检查）

        Args:
            file: {"file": "xxx", "content": "..."}

        Returns:
            {"success": bool, "errors": [...]}
        """
        pass

    @abstractmethod
    def verify_functionality(self, file: Dict[str, Any],
                             test_cases: List[Dict] = None) -> Dict[str, Any]:
        """
        功能验证（运行测试）

        Args:
            file: 文件信息
            test_cases: 测试用例列表

        Returns:
            {"success": bool, "passed": int, "failed": int, "errors": [...]}
        """
        pass

    def verify(self, original_file: Dict[str, Any],
               fixed_file: Dict[str, Any],
               original_issues: List[Dict],
               test_cases: List[Dict] = None,
               scanner=None) -> VerificationResult:
        """
        完整验证流程

        Args:
            original_file: 原始文件
            fixed_file: 修复后文件
            original_issues: 原始问题列表
            test_cases: 测试用例
            scanner: 扫描器实例（用于重新扫描）

        Returns:
            VerificationResult对象
        """
        filename = fixed_file.get("file", "")

        result = VerificationResult(
            file=filename,
            language=self.language.value,
            compile_success=False,
            test_success=False,
            remaining_issues=[],
            new_issues=[],
            fix_rate=0.0
        )

        # ✅ 第0步：获取原始问题数量
        original_count = self._get_original_issue_count(original_issues, fixed_file)
        print(f"[BaseVerifier] 原始问题总数: {original_count}")

        # ✅ 第1步：语法验证
        try:
            syntax_result = self.verify_syntax(fixed_file)
            result.compile_success = syntax_result.get("success", False)

            if not result.compile_success:
                result.error_message = "编译失败: " + str(syntax_result.get("errors", []))
                print(f"[BaseVerifier] ❌ 编译失败")
            else:
                print(f"[BaseVerifier] ✅ 编译成功")
        except Exception as e:
            result.error_message = f"语法验证失败: {str(e)}"
            print(f"[BaseVerifier] 语法验证异常: {e}")
            import traceback
            traceback.print_exc()

        # ✅ 第2步：重新扫描（检查剩余问题和新增问题）
        remaining_issues = []
        new_issues = []
        scan_success = False

        if scanner:
            try:
                print(f"[BaseVerifier] 开始重新扫描...")

                # ✅ 修复：根据 scanner 的实际接口调用
                rescan_result = self._safe_scan(scanner, fixed_file)

                if rescan_result:
                    remaining_issues, new_issues = self._compare_issues(
                        original_issues,
                        rescan_result
                    )

                    result.remaining_issues = remaining_issues
                    result.new_issues = new_issues
                    scan_success = True

                    print(f"[BaseVerifier] 重新扫描完成:")
                    print(f"[BaseVerifier]   - 剩余问题: {len(remaining_issues)} 个")
                    print(f"[BaseVerifier]   - 新增问题: {len(new_issues)} 个")
                else:
                    print(f"[BaseVerifier] 重新扫描返回空结果")

            except Exception as e:
                result.error_message = f"重新扫描失败: {str(e)}"
                print(f"[BaseVerifier] 重新扫描异常: {e}")
                import traceback
                traceback.print_exc()

        # ✅ 第3步：计算修复率（修复数/总数）
        if scan_success:
            # 基于实际扫描结果计算
            remaining_count = len(remaining_issues)
            fixed_count = max(0, original_count - remaining_count)

            if original_count > 0:
                result.fix_rate = (fixed_count / original_count) * 100
            else:
                result.fix_rate = 100.0 if remaining_count == 0 else 0.0

            print(f"[BaseVerifier] 修复率计算（实际）:")
            print(f"[BaseVerifier]   原始问题: {original_count} 个")
            print(f"[BaseVerifier]   剩余问题: {remaining_count} 个")
            print(f"[BaseVerifier]   修复问题: {fixed_count} 个")
            print(f"[BaseVerifier]   修复率: {result.fix_rate:.1f}%")

            if len(new_issues) > 0:
                print(f"[BaseVerifier]   ⚠️ 新增问题: {len(new_issues)} 个（LLM引入）")
        else:
            # 扫描失败时的降级策略
            result.fix_rate = self._estimate_fix_rate(
                original_count,
                result.compile_success,
                fixed_file
            )
            print(f"[BaseVerifier] 修复率估算: {result.fix_rate:.1f}%")

        # ✅ 第4步：功能验证
        if test_cases:
            try:
                test_result = self.verify_functionality(fixed_file, test_cases)
                result.test_success = test_result.get("success", False)

                if not result.test_success:
                    if result.error_message:
                        result.error_message += "; 测试失败: " + str(test_result.get("errors", []))
                    else:
                        result.error_message = "测试失败: " + str(test_result.get("errors", []))
            except Exception as e:
                if result.error_message:
                    result.error_message += f"; 功能验证失败: {str(e)}"
                else:
                    result.error_message = f"功能验证失败: {str(e)}"
                print(f"[BaseVerifier] 功能验证异常: {e}")
        else:
            result.test_success = True  # 无测试用例，默认通过

        return result

    def _get_original_issue_count(self, original_issues: List[Dict],
                                  fixed_file: Dict[str, Any]) -> int:
        """获取原始问题数量"""
        # 方法1：使用传入的 original_issues
        if original_issues:
            count = len(original_issues)
            print(f"[BaseVerifier] 从 original_issues 获取: {count} 个问题")
            return count

        # 方法2：从 fixed_file 获取
        if "original_issues_count" in fixed_file:
            count = fixed_file.get("original_issues_count", 0)
            print(f"[BaseVerifier] 从 fixed_file.original_issues_count 获取: {count} 个问题")
            return count

        if "original_issues" in fixed_file:
            orig_issues = fixed_file.get("original_issues", [])
            if isinstance(orig_issues, list):
                count = len(orig_issues)
                print(f"[BaseVerifier] 从 fixed_file.original_issues 获取: {count} 个问题")
                return count

        # 方法3：使用 fixed_count
        if "fixed_count" in fixed_file:
            count = fixed_file.get("fixed_count", 0)
            print(f"[BaseVerifier] 从 fixed_file.fixed_count 推断: {count} 个问题")
            return count

        return 0

    def _safe_scan(self, scanner, fixed_file: Dict[str, Any]) -> Optional[List[Dict]]:
        """
        安全地调用 scanner（兼容多种接口）

        Returns:
            问题列表，失败返回 None
        """
        try:
            # ✅ 尝试方法1：scanner.scan([files])
            try:
                rescan_result = scanner.scan([fixed_file])
                return self._extract_issues_from_scan_result(rescan_result)
            except TypeError:
                pass

            # ✅ 尝试方法2：scanner.files = [...]; scanner.scan()
            try:
                scanner.files = [fixed_file]
                rescan_result = scanner.scan()
                return self._extract_issues_from_scan_result(rescan_result)
            except (TypeError, AttributeError):
                pass

            # ✅ 尝试方法3：scanner.set_files([...]); scanner.scan()
            try:
                if hasattr(scanner, 'set_files'):
                    scanner.set_files([fixed_file])
                    rescan_result = scanner.scan()
                    return self._extract_issues_from_scan_result(rescan_result)
            except (TypeError, AttributeError):
                pass

            # ✅ 尝试方法4：直接调用 scanner.scan_file(file)
            try:
                if hasattr(scanner, 'scan_file'):
                    rescan_result = scanner.scan_file(fixed_file)
                    return self._extract_issues_from_scan_result(rescan_result)
            except (TypeError, AttributeError):
                pass

            raise Exception("无法找到兼容的 scanner 接口")

        except Exception as e:
            print(f"[BaseVerifier] Scanner 调用失败: {e}")
            return None

    def _extract_issues_from_scan_result(self, rescan_result) -> List[Dict]:
        """从扫描结果中提取问题列表"""
        if not rescan_result:
            return []

        # 如果是 dict，尝试从不同的键获取
        if isinstance(rescan_result, dict):
            issues = (
                    rescan_result.get("builtin", []) or
                    rescan_result.get("issues", []) or
                    rescan_result.get("findings", []) or
                    rescan_result.get("results", []) or
                    []
            )
            # 如果 dict 本身就是按文件组织的，提取所有问题
            if not issues and "files" not in rescan_result:
                for key, value in rescan_result.items():
                    if isinstance(value, list):
                        issues.extend(value)
            return issues

        # 如果是 list，直接返回
        if isinstance(rescan_result, list):
            return rescan_result

        return []

    def _compare_issues(self, original_issues: List[Dict],
                        current_issues: List[Dict]) -> tuple:
        """
        比较原始问题和当前问题，区分剩余问题和新增问题

        Returns:
            (remaining_issues, new_issues)
        """
        # 构建原始问题的特征集合（用于匹配）
        original_signatures = set()
        for issue in original_issues:
            sig = self._get_issue_signature(issue)
            original_signatures.add(sig)

        remaining_issues = []
        new_issues = []

        for issue in current_issues:
            sig = self._get_issue_signature(issue)
            if sig in original_signatures:
                # 原始问题仍然存在
                remaining_issues.append(issue)
            else:
                # 新增问题（LLM引入）
                new_issues.append(issue)

        return remaining_issues, new_issues

    def _get_issue_signature(self, issue: Dict[str, Any]) -> str:
        """
        生成问题的唯一签名（用于匹配）

        使用 rule_id + line 作为签名，如果没有则使用 message 的 hash
        """
        rule_id = issue.get("rule_id", "")
        line = issue.get("line", 0)
        message = issue.get("message", "")

        if rule_id and line:
            return f"{rule_id}:{line}"
        elif rule_id:
            return f"{rule_id}:{hash(message) % 10000}"
        else:
            return f"unknown:{line}:{hash(message) % 10000}"

    def _estimate_fix_rate(self, original_count: int,
                           compile_success: bool,
                           fixed_file: Dict[str, Any]) -> float:
        """
        估算修复率（当扫描失败时）
        """
        if original_count == 0:
            return 100.0

        # 根据编译状态和修复标记估算
        if compile_success and fixed_file.get("status") == "fixed":
            # 编译成功 + 修复标记 = 假设 90% 修复
            return 90.0
        elif compile_success:
            # 仅编译成功 = 假设 70% 修复
            return 70.0
        else:
            # 编译失败 = 假设 0% 修复
            return 0.0