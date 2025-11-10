# verifiers/python_verifier.py
"""
PythonVerifier - Python代码验证器
"""
import ast
import sys
import os
from typing import Dict, List, Any

from .base_verifier import BaseVerifier, Language


class PythonVerifier(BaseVerifier):
    """Python专用验证器"""

    def __init__(self):
        super().__init__(Language.PYTHON)

    def verify_syntax(self, file: Dict[str, Any]) -> Dict[str, Any]:
        """语法验证：使用Python AST解析"""
        content = file.get("content", "")
        filename = file.get("file", "temp.py")

        result = {
            "success": False,
            "errors": []
        }

        print(f"[PythonVerifier] 开始语法验证: {filename}")

        try:
            # 使用 compile 而不是 ast.parse，能捕获更多错误
            compile(content, filename, 'exec')
            result["success"] = True
            print(f"[PythonVerifier] ✅ 语法检查通过")

        except SyntaxError as e:
            result["errors"].append({
                "line": e.lineno,
                "column": e.offset,
                "message": e.msg,
                "text": e.text
            })
            print(f"[PythonVerifier] ❌ 语法错误: 第{e.lineno}行 - {e.msg}")

        except IndentationError as e:
            result["errors"].append({
                "line": e.lineno,
                "column": e.offset,
                "message": f"缩进错误: {e.msg}",
                "text": e.text
            })
            print(f"[PythonVerifier] ❌ 缩进错误: 第{e.lineno}行 - {e.msg}")

        except Exception as e:
            result["errors"].append({
                "line": 0,
                "message": str(e)
            })
            print(f"[PythonVerifier] ❌ 验证异常: {e}")

        return result

    def verify_functionality(self, file: Dict[str, Any],
                             test_cases: List[Dict] = None) -> Dict[str, Any]:
        """功能验证：运行测试用例"""
        result = {
            "success": True,
            "passed": 0,
            "failed": 0,
            "errors": []
        }

        if not test_cases:
            print(f"[PythonVerifier] 无测试用例，跳过功能验证")
            return result

        print(f"[PythonVerifier] 开始功能验证: {len(test_cases)} 个测试用例")

        content = file.get("content", "")
        filename = file.get("file", "temp.py")

        try:
            # 编译代码
            code_obj = compile(content, filename, 'exec')

            # 创建执行环境
            exec_globals = {}
            exec(code_obj, exec_globals)

            # 运行测试用例
            for i, test_case in enumerate(test_cases):
                try:
                    func_name = test_case.get("function", "main")
                    inputs = test_case.get("input", [])
                    expected = test_case.get("expected_output")

                    if func_name not in exec_globals:
                        result["failed"] += 1
                        result["errors"].append({
                            "test_case": i + 1,
                            "error": f"函数 {func_name} 不存在"
                        })
                        continue

                    func = exec_globals[func_name]

                    # 执行函数
                    if isinstance(inputs, list):
                        actual = func(*inputs)
                    else:
                        actual = func(inputs)

                    # 比较结果
                    if actual == expected:
                        result["passed"] += 1
                        print(f"[PythonVerifier] 测试 {i + 1}: ✅ 通过")
                    else:
                        result["failed"] += 1
                        result["errors"].append({
                            "test_case": i + 1,
                            "expected": expected,
                            "actual": actual
                        })
                        print(f"[PythonVerifier] 测试 {i + 1}: ❌ 失败 (期望: {expected}, 实际: {actual})")

                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append({
                        "test_case": i + 1,
                        "error": str(e)
                    })
                    print(f"[PythonVerifier] 测试 {i + 1}: ❌ 异常 - {e}")

            result["success"] = result["failed"] == 0

        except Exception as e:
            result["success"] = False
            result["errors"].append({
                "error": f"执行失败: {str(e)}"
            })
            print(f"[PythonVerifier] 功能验证失败: {e}")

        print(f"[PythonVerifier] 功能验证完成: {result['passed']}/{len(test_cases)} 通过")

        return result