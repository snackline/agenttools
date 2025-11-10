# verifiers/java_verifier.py
"""
JavaVerifier - Java代码验证器
"""
import os
import re
import tempfile
import shutil
import subprocess
from typing import Dict, List, Any

from .base_verifier import BaseVerifier, Language


class JavaVerifier(BaseVerifier):
    """Java专用验证器"""

    def __init__(self):
        super().__init__(Language.JAVA)

    def verify_syntax(self, file: Dict[str, Any]) -> Dict[str, Any]:
        """语法验证：使用javac编译"""
        content = file.get("content", "")
        filename = file.get("file", "temp.java")

        result = {
            "success": False,
            "errors": []
        }

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="java_verify_")

        print(f"[JavaVerifier] 开始语法验证: {filename}")
        print(f"[JavaVerifier] 临时目录: {tmp_dir}")

        try:
            # 写入文件
            filepath = os.path.join(tmp_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"[JavaVerifier] 写入文件: {filepath}")

            # 编译
            compile_cmd = ["javac", "-encoding", "UTF-8", "-d", tmp_dir, filepath]
            print(f"[JavaVerifier] 编译命令: {' '.join(compile_cmd)}")

            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if compile_result.returncode == 0:
                result["success"] = True
                print(f"[JavaVerifier] 编译成功")
            else:
                # 解析编译错误
                stderr = compile_result.stderr
                print(f"[JavaVerifier] 编译失败:\n{stderr}")

                for line in stderr.split('\n'):
                    if '.java:' in line:
                        match = re.search(r':(\d+):\s*error:\s*(.+)', line)
                        if match:
                            result["errors"].append({
                                "line": int(match.group(1)),
                                "message": match.group(2)
                            })

        except subprocess.TimeoutExpired:
            result["errors"].append({"line": 0, "message": "编译超时"})
            print(f"[JavaVerifier] 编译超时")
        except FileNotFoundError:
            result["errors"].append({"line": 0, "message": "javac未找到，请确保已安装JDK"})
            print(f"[JavaVerifier] javac未找到")
        except Exception as e:
            result["errors"].append({"line": 0, "message": str(e)})
            print(f"[JavaVerifier] 验证异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result

    def verify_functionality(self, file: Dict[str, Any],
                             test_cases: List[Dict] = None) -> Dict[str, Any]:
        """功能验证：运行JUnit测试（简化版）"""
        result = {
            "success": True,
            "passed": 0,
            "failed": 0,
            "errors": []
        }

        # Java功能验证较复杂，需要JUnit框架
        # 这里仅做简单的编译+运行验证
        if not test_cases:
            return result

        print(f"[JavaVerifier] 功能验证: {len(test_cases)} 个测试用例")

        content = file.get("content", "")
        filename = file.get("file", "Main.java")

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="java_run_")

        try:
            # 写入文件
            filepath = os.path.join(tmp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

                # 编译
            compile_cmd = ["javac", "-encoding", "UTF-8", "-d", tmp_dir, filepath]
            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if compile_result.returncode != 0:
                result["success"] = False
                result["errors"].append({"message": "编译失败"})
                return result

                # 获取类名
            class_match = re.search(r'public\s+class\s+(\w+)', content)
            if not class_match:
                result["errors"].append({"message": "未找到public类"})
                return result

            class_name = class_match.group(1)

            # 运行测试用例
            for i, test_case in enumerate(test_cases):
                test_input = test_case.get("input", "")
                expected_output = test_case.get("expected_output", "")

                try:
                    run_cmd = ["java", "-cp", tmp_dir, class_name]
                    run_result = subprocess.run(
                        run_cmd,
                        input=test_input,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        cwd=tmp_dir
                    )

                    actual_output = run_result.stdout.strip()

                    if actual_output == expected_output:
                        result["passed"] += 1
                    else:
                        result["failed"] += 1
                        result["errors"].append({
                            "test_case": i + 1,
                            "expected": expected_output,
                            "actual": actual_output
                        })

                except subprocess.TimeoutExpired:
                    result["failed"] += 1
                    result["errors"].append({
                        "test_case": i + 1,
                        "error": "超时"
                    })
                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append({
                        "test_case": i + 1,
                        "error": str(e)
                    })

            result["success"] = result["failed"] == 0

        except Exception as e:
            result["success"] = False
            result["errors"].append({"message": str(e)})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result