#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SWE-bench集成测试运行器
"""
import json
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging
 
# 导入现有Agent系统
from agents.orchestrator_agent import OrchestratorAgent
from utils.language_detector import LanguageDetector
 
class SWEBenchRunner:
    """SWE-bench测试运行器"""
    
    def __init__(self, swe_bench_path: str, output_dir: str = "swe_bench_results"):
        self.swe_bench_path = Path(swe_bench_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.output_dir / 'swe_bench.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def load_swe_bench_dataset(self, split: str = "test") -> List[Dict]:
        """加载SWE-bench数据集"""
        dataset_file = self.swe_bench_path / f"{split}.json"
        if not dataset_file.exists():
            # 尝试其他可能的文件名
            for pattern in ["swe-bench.json", "dataset.json", "swe_bench_test.json"]:
                dataset_file = self.swe_bench_path / pattern
                if dataset_file.exists():
                    break
            else:
                raise FileNotFoundError(f"在 {self.swe_bench_path} 中找不到数据集文件")
        
        with open(dataset_file, 'r', encoding='utf-8') as f:
            dataset = json.load(f)
        
        self.logger.info(f"加载了 {len(dataset)} 个测试用例")
        return dataset
    
    def setup_repository(self, test_case: Dict) -> str:
        """设置测试仓库环境"""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = Path(temp_dir) / "repo"
            repo_dir.mkdir()
            
            # 克隆仓库
            repo_url = test_case.get("repo", "")
            commit_id = test_case.get("base_commit", "")
            
            if repo_url and commit_id:
                self.logger.info(f"克隆仓库: {repo_url} @ {commit_id}")
                subprocess.run([
                    "git", "clone", repo_url, str(repo_dir)
                ], check=True, capture_output=True)
                
                subprocess.run([
                    "git", "checkout", commit_id
                ], cwd=repo_dir, check=True, capture_output=True)
            
            return str(repo_dir)
    
    def extract_files_from_test_case(self, test_case: Dict) -> List[Dict]:
        """从测试用例中提取文件信息"""
        files = []
        
        # 尝试不同的字段名来获取文件内容
        for file_field in ["files", "test_patch", "patch", "code_files"]:
            if file_field in test_case:
                file_data = test_case[file_field]
                if isinstance(file_data, dict):
                    for filename, content in file_data.items():
                        files.append({
                            "path": filename,
                            "name": filename,
                            "content": content,
                            "size": len(content)
                        })
                elif isinstance(file_data, list):
                    files.extend(file_data)
        
        return files
    
    def run_single_test_case(self, test_case: Dict, config: Dict) -> Dict[str, Any]:
        """运行单个测试用例"""
        instance_id = test_case.get("instance_id", "unknown")
        self.logger.info(f"开始处理测试用例: {instance_id}")
        
        try:
            # 1. 提取文件
            files = self.extract_files_from_test_case(test_case)
            if not files:
                return {
                    "instance_id": instance_id,
                    "success": False,
                    "error": "无法从测试用例中提取文件"
                }
            
            # 2. 设置仓库环境（可选）
            repo_dir = None
            try:
                repo_dir = self.setup_repository(test_case)
            except Exception as e:
                self.logger.warning(f"设置仓库失败，使用内存模式: {e}")
            
            # 3. 获取问题描述
            problem_statement = test_case.get("problem_statement", "")
            
            # 4. 调用现有Agent系统
            orchestrator = OrchestratorAgent(config)
            
            input_data = {
                "files": files,
                "user_request": problem_statement,
                "repo_dir": repo_dir,
                "test_case": test_case
            }
            
            # 执行Agent工作流
            result = orchestrator.run(input_data)
            
            # 5. 运行验证（如果有测试）
            verification_result = {}
            if "test_cases" in test_case:
                verification_result = self.run_verification(repo_dir, test_case)
            
            return {
                "instance_id": instance_id,
                "success": result.get("success", False),
                "agent_result": result,
                "verification": verification_result,
                "files_processed": len(files)
            }
            
        except Exception as e:
            self.logger.error(f"处理测试用例 {instance_id} 失败: {e}")
            return {
                "instance_id": instance_id,
                "success": False,
                "error": str(e)
            }
    
    def run_verification(self, repo_dir: Optional[str], test_case: Dict) -> Dict[str, Any]:
        """运行测试验证"""
        if not repo_dir:
            return {"status": "skipped", "reason": "no_repo_dir"}
        
        try:
            # 运行测试命令（根据测试用例配置）
            test_commands = test_case.get("test_commands", [])
            if not test_commands:
                return {"status": "skipped", "reason": "no_test_commands"}
            
            results = []
            for cmd in test_commands:
                result = subprocess.run(
                    cmd, shell=True, cwd=repo_dir,
                    capture_output=True, text=True, timeout=300
                )
                results.append({
                    "command": cmd,
                    "return_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                })
            
            return {
                "status": "completed",
                "results": results,
                "passed": all(r["return_code"] == 0 for r in results)
            }
            
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "reason": "test_timeout"}
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def run_swe_bench_test(self, 
                          split: str = "test", 
                          max_instances: Optional[int] = None,
                          config: Optional[Dict] = None) -> Dict[str, Any]:
        """运行完整的SWE-bench测试"""
        
        # 默认配置
        if config is None:
            config = {
                "scanner": {"enable_external": True, "enable_dynamic": True},
                "analyzer": {},
                "fixer": {"use_rules": True, "use_llm": True},
                "verifier": {"timeout": 60}
            }
        
        # 加载数据集
        dataset = self.load_swe_bench_dataset(split)
        
        if max_instances:
            dataset = dataset[:max_instances]
        
        self.logger.info(f"开始运行SWE-bench测试，共 {len(dataset)} 个实例")
        
        results = []
        successful = 0
        failed = 0
        
        for i, test_case in enumerate(dataset, 1):
            self.logger.info(f"进度: {i}/{len(dataset)}")
            
            result = self.run_single_test_case(test_case, config)
            results.append(result)
            
            if result["success"]:
                successful += 1
            else:
                failed += 1
            
            # 保存中间结果
            if i % 10 == 0:
                self.save_results(results, f"partial_results_{i}.json")
        
        # 计算统计信息
        stats = {
            "total": len(dataset),
            "successful": successful,
            "failed": failed,
            "success_rate": successful / len(dataset) if dataset else 0
        }
        
        final_result = {
            "config": config,
            "statistics": stats,
            "results": results
        }
        
        # 保存最终结果
        self.save_results(final_result, f"swe_bench_{split}_results.json")
        
        self.logger.info(f"SWE-bench测试完成: {successful}/{len(dataset)} 成功")
        
        return final_result
    
    def save_results(self, results: Dict[str, Any], filename: str):
        """保存结果到文件"""
        output_file = self.output_dir / filename
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        self.logger.info(f"结果已保存到: {output_file}")
 
 
def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="运行SWE-bench测试")
    parser.add_argument("--swe-bench-path", required=True, 
                       help="SWE-bench数据集路径")
    parser.add_argument("--split", default="test", 
                       help="数据集分割 (test/dev)")
    parser.add_argument("--max-instances", type=int, 
                       help="最大测试实例数")
    parser.add_argument("--output-dir", default="swe_bench_results",
                       help="输出目录")
    
    args = parser.parse_args()
    
    runner = SWEBenchRunner(args.swe_bench_path, args.output_dir)
    
    # 运行测试
    result = runner.run_swe_bench_test(
        split=args.split,
        max_instances=args.max_instances
    )
    
    print(f"\n=== 测试完成 ===")
    print(f"总计: {result['statistics']['total']}")
    print(f"成功: {result['statistics']['successful']}")
    print(f"失败: {result['statistics']['failed']}")
    print(f"成功率: {result['statistics']['success_rate']:.2%}")
 
 
if __name__ == "__main__":
    main()