# verifiers/cpp_verifier.py
"""
CppVerifier - C/C++代码验证器
"""
import os
import tempfile
import shutil
import subprocess
from typing import Dict, List, Any

from .base_verifier import BaseVerifier, Language


class CppVerifier(BaseVerifier):
    """C/C++专用验证器"""

    def __init__(self, language: Language = Language.CPP):
        super().__init__(language)

    def verify_syntax(self, file: Dict[str, Any]) -> Dict[str, Any]:
        """语法验证：使用gcc/g++编译"""
        content = file.get("content", "")
        filename = file.get("file", "temp.cpp")

        result = {
            "success": False,
            "errors": []
        }

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="cpp_verify_")

        print(f"[CppVerifier] 开始语法验证: {filename}")
        print(f"[CppVerifier] 临时目录: {tmp_dir}")

        try:
            # 写入文件
            filepath = os.path.join(tmp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"[CppVerifier] 写入文件: {filepath}")

            # 选择编译器
            compiler = "g++" if self.language == Language.CPP else "gcc"
            std_flag = "-std=c++17" if self.language == Language.CPP else "-std=c11"

            # 编译
            compile_cmd = [
                compiler,
                std_flag,
                "-Wall",
                "-Wextra",
                "-c",  # 只编译不链接
                filepath,
                "-o", os.path.join(tmp_dir, "output.o")
            ]

            print(f"[CppVerifier] 编译命令: {' '.join(compile_cmd)}")

            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp_dir
            )

            if compile_result.returncode == 0:
                result["success"] = True
                print(f"[CppVerifier] 编译成功")
            else:
                # 解析编译错误
                stderr = compile_result.stderr
                print(f"[CppVerifier] 编译失败:\n{stderr}")

                for line in stderr.split('\n'):
                    if 'error:' in line:
                        result["errors"].append({"message": line.strip()})

        except subprocess.TimeoutExpired:
            result["errors"].append({"message": "编译超时"})
            print(f"[CppVerifier] 编译超时")
        except FileNotFoundError:
            result["errors"].append({"message": f"{compiler}未找到，请确保已安装编译器"})
            print(f"[CppVerifier] {compiler}未找到")
        except Exception as e:
            result["errors"].append({"message": str(e)})
            print(f"[CppVerifier] 验证异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result

    def verify_functionality(self, file: Dict[str, Any],
                             test_cases: List[Dict] = None) -> Dict[str, Any]:
        """功能验证：编译并运行"""
        result = {
            "success": False,
            "passed": 0,
            "failed": 0,
            "errors": []
        }

        if not test_cases:
            result["success"] = True
            return result

        print(f"[CppVerifier] 功能验证: {len(test_cases)} 个测试用例")

        content = file.get("content", "")
        filename = file.get("file", "temp.cpp")

        # 创建临时目录
        tmp_dir = tempfile.mkdtemp(prefix="cpp_run_")

        try:
            # 写入文件
            filepath = os.path.join(tmp_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            # 编译
            compiler = "g++" if self.language == Language.CPP else "gcc"
            std_flag = "-std=c++17" if self.language == Language.CPP else "-std=c11"
            output_file = os.path.join(tmp_dir, "program")

            compile_cmd = [compiler, std_flag, filepath, "-o", output_file]

            print(f"[CppVerifier] 编译命令: {' '.join(compile_cmd)}")

            compile_result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=tmp_dir
            )

            if compile_result.returncode != 0:
                result["errors"].append({"error": "编译失败"})
                print(f"[CppVerifier] 编译失败")
                return result

            print(f"[CppVerifier] 编译成功，开始运行测试")

            # 运行测试用例
            for i, test_case in enumerate(test_cases):
                test_input = test_case.get("input", "")
                expected_output = test_case.get("expected_output", "")

                try:
                    run_result = subprocess.run(
                        [output_file],
                        input=test_input,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        cwd=tmp_dir
                    )

                    actual_output = run_result.stdout.strip()

                    if actual_output == expected_output:
                        result["passed"] += 1
                        print(f"[CppVerifier] 测试用例 {i + 1}: 通过")
                    else:
                        result["failed"] += 1
                        result["errors"].append({
                            "test_case": i + 1,
                            "expected": expected_output,
                            "actual": actual_output
                        })
                        print(f"[CppVerifier] 测试用例 {i + 1}: 失败")

                except subprocess.TimeoutExpired:
                    result["failed"] += 1
                    result["errors"].append({
                        "test_case": i + 1,
                        "error": "超时"
                    })
                    print(f"[CppVerifier] 测试用例 {i + 1}: 超时")
                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append({
                        "test_case": i + 1,
                        "error": str(e)
                    })
                    print(f"[CppVerifier] 测试用例 {i + 1}: 异常 - {e}")

            result["success"] = result["failed"] == 0

        except Exception as e:
            result["errors"].append({"error": str(e)})
            print(f"[CppVerifier] 功能验证异常: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return result