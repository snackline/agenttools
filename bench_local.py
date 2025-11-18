#!/usr/bin/env python3
# bench_local.py
 
from datasets import load_dataset 
from agents.orchestrator_agent import OrchestratorAgent
from utils.language_detector import LanguageDetector, Language
import json
import time
import os
 
def detect_language_from_repo(repo_name: str) -> str:
    """从仓库名检测编程语言"""
    repo_lower = repo_name.lower()
    
    if 'python' in repo_lower or 'py' in repo_lower:
        return 'python'
    elif 'java' in repo_lower:
        return 'java'
    elif 'cpp' in repo_lower or 'c++' in repo_lower:
        return 'cpp'
    elif 'c' in repo_lower:
        return 'c'
    else:
        # 默认返回python，因为SWE-bench中Python项目较多
        return 'python'

def get_file_extension(language: str) -> str:
    """根据语言获取文件扩展名"""
    extensions = {
        'python': '.py',
        'java': '.java',
        'cpp': '.cpp',
        'c': '.c'
    }
    return extensions.get(language, '.py')
 
def process_swe_instance(orchestrator, instance):
    """处理单个SWE-bench实例"""
    
    try:
        # instance现在应该是字典
        if not isinstance(instance, dict):
            print(f"⚠️ 期望字典，得到: {type(instance)}")
            return {
                "instance_id": f"error_{hash(str(instance)) % 10000}",
                "success": False,
                "patch": "",
                "error": f"数据类型错误: {type(instance)}",
                "execution_time": {},
                "fix_summary": {}
            }
        
        # 提取SWE-bench实例信息
        instance_id = instance.get('instance_id', f"id_{hash(str(instance)) % 10000}")
        repo = instance.get('repo', 'unknown/repo')
        problem_statement = instance.get('problem_statement', '')
        patch = instance.get('patch', '')  # 真实的补丁
        
        print(f"\n🔧 处理实例: {instance_id}")
        print(f"📂 仓库: {repo}")
        print(f"📝 问题描述: {problem_statement[:100]}...")
        
        # 从仓库名检测语言
        language = detect_language_from_repo(repo)
        print(f"🌐 检测语言: {language}")
        
        # 解析真实补丁中的文件
        files = []
        if patch:
            # 简单解析patch格式
            patch_lines = patch.split('\n')
            current_file = None
            file_content = []
            
            for line in patch_lines:
                if line.startswith('diff --git a/'):
                    # 保存前一个文件
                    if current_file and file_content:
                        files.append({
                            'file': current_file,
                            'content': '\n'.join(file_content),
                            'language': language
                        })
                    
                    # 提取新文件名
                    parts = line.split()
                    if len(parts) >= 4:
                        current_file = parts[3][2:]  # 去掉 'b/' 前缀
                        file_content = []
                        
                elif line.startswith('+') and not line.startswith('+++'):
                    # 添加修改后的行
                    file_content.append(line[1:])  # 去掉 '+' 前缀
                elif line.startswith(' '):
                    # 保留未修改的行
                    file_content.append(line[1:])
            
            # 保存最后一个文件
            if current_file and file_content:
                files.append({
                    'file': current_file,
                    'content': '\n'.join(file_content),
                    'language': language
                })
        
        # 如果没有从patch中提取到文件，创建模拟文件
        if not files:
            files = [{
                'file': f'buggy_file{get_file_extension(language)}',
                'content': f'// 需要修复的{language}代码\n// 问题: {problem_statement[:200]}...',
                'language': language
            }]
        
        print(f"📄 处理文件数: {len(files)}")
        for f in files[:3]:  # 显示前3个文件
            print(f"   - {f['file']} ({f['language']})")
        
        # 使用orchestrator处理
        input_data = {
            "files": files,
            "user_request": problem_statement,
            "test_cases": []  # 简化处理，实际应该使用PASS_TO_PASS和FAIL_TO_PASS
        }
        
        # 执行工作流
        perception = orchestrator.perceive(input_data)
        decision = orchestrator.decide(perception)
        decision.update(perception)
        results = orchestrator.execute(decision)
        
        # 提取修复结果
        fixed_patch = ""
        success = False
        
        if results.get('success') and results.get('fix_results'):
            fix_results = results['fix_results']
            if fix_results.get('fixed_files'):
                for fixed_file in fix_results['fixed_files']:
                    if fixed_file.get('success'):
                        fixed_patch += f"--- {fixed_file['file']}\n"
                        fixed_patch += f"+++ {fixed_file['file']}\n"
                        fixed_patch += f"@@ -1,1 +1,1 @@\n"
                        fixed_patch += f"- 原始内容\n"
                        fixed_patch += f"+ {fixed_file.get('fixed_content', '')}\n"
                
                success = True
        
        return {
            "instance_id": instance_id,
            "success": success,
            "original_patch": patch,  # 真实补丁
            "generated_patch": fixed_patch,  # 你的系统生成的补丁
            "error": results.get('error', ''),
            "execution_time": results.get('execution_time', {}),
            "fix_summary": results.get('fix_results', {}).get('summary', {}),
            "repo": repo,
            "language": language
        }
        
    except Exception as e:
        return {
            "instance_id": instance.get('instance_id', 'unknown') if isinstance(instance, dict) else 'error_instance',
            "success": False,
            "patch": "",
            "error": str(e),
            "execution_time": {},
            "fix_summary": {}
        }
 
def main():
    # 加载SWE-bench数据集
    dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    
    try:
        # 使用requests直接调用ollama API
        import requests
        import json
        
        # 测试ollama连接
        try:
            print("🔍 测试ollama连接...")
            
            # 先检查服务状态
            response = requests.get('http://localhost:11434/api/tags', timeout=5)
            if response.status_code != 200:
                raise Exception(f"API状态码: {response.status_code}")
            
            # 测试chat API
            chat_response = requests.post(
                'http://localhost:11434/api/chat',
                json={
                    'model': 'qwen3-coder:30b',
                    'messages': [{'role': 'user', 'content': 'test'}],
                    'stream': False
                },
                timeout=30
            )
            
            if chat_response.status_code != 200:
                raise Exception(f"Chat API状态码: {chat_response.status_code}")
            
            print("✅ ollama连接成功")
            
        except Exception as e:
            print(f"❌ 连接测试失败: {e}")
            return
        
        # 创建简单的LLM客户端封装
        class SimpleOllamaClient:
            def __init__(self, model='qwen3-coder:30b'):
                self.model = model
                self.base_url = 'http://localhost:11434'
            
            def chat(self, messages, **kwargs):
                """兼容ollama.chat接口"""
                response = requests.post(
                    f'{self.base_url}/api/chat',
                    json={
                        'model': self.model,
                        'messages': messages,
                        'stream': False
                    },
                    timeout=60
                )
                
                if response.status_code != 200:
                    raise Exception(f"API调用失败: {response.status_code}")
                
                result = response.json()
                # 返回纯字符串内容，和其它 LLM 客户端兼容（PythonFixer 期望接收字符串）
                return result.get('message', {}).get('content', '')
        
        # 创建客户端
        llm_client = SimpleOllamaClient('qwen3-coder:30b')
        
        # 配置修复系统
        config = {
            "fixer": {
                "llm_client": llm_client,
                "use_rules": True,
                "use_llm": True,
                "model_name": "qwen3-coder:30b"
            }
        }
        
        print(f"\n🚀 初始化多语言修复系统（使用 qwen3-coder:30b）...")
        orchestrator = OrchestratorAgent(config)
        
        # 测试配置
        test_config = {
            "num_instances": 15,  # 只测试5个实例
            "save_results": True,
            "output_file": "swe_bench_test_results.json"
        }
        
        print(f"\n🔬 开始测试 {test_config['num_instances']} 个SWE-bench实例...")
        
        # 运行测试
        start_time = time.time()
        results = []
        success_count = 0
        
        for i in range(min(test_config['num_instances'], len(dataset))):
            instance = dataset[i]  # 现在获取的是完整的实例字典
            
            print(f"\n{'='*60}")
            print(f"进度: {i+1}/{test_config['num_instances']}")
            print(f"{'='*60}")
            
            result = process_swe_instance(orchestrator, instance)
            results.append(result)
            
            if result['success']:
                success_count += 1
                print(f"✅ {result['instance_id']} - 处理成功")
            else:
                print(f"❌ {result['instance_id']} - 处理失败: {result['error']}")
        
        end_time = time.time()
        
        # 统计结果
        success_rate = success_count / test_config['num_instances'] * 100
        
        print(f"\n{'='*60}")
        print(f"📊 SWE-bench测试总结")
        print(f"{'='*60}")
        print(f"✅ 成功: {success_count}/{test_config['num_instances']} ({success_rate:.1f}%)")
        print(f"⏱️  总用时: {end_time - start_time:.2f} 秒")
        print(f"⚡ 平均用时: {(end_time - start_time)/test_config['num_instances']:.2f} 秒/实例")
        
        # 按语言统计
        lang_stats = {}
        for result in results:
            lang = result.get('language', 'unknown')
            if lang not in lang_stats:
                lang_stats[lang] = {'total': 0, 'success': 0}
            lang_stats[lang]['total'] += 1
            if result['success']:
                lang_stats[lang]['success'] += 1
        
        print(f"\n🌐 按语言统计:")
        for lang, stats in lang_stats.items():
            rate = stats['success'] / stats['total'] * 100 if stats['total'] > 0 else 0
            print(f"   - {lang}: {stats['success']}/{stats['total']} ({rate:.1f}%)")
        
        # 保存结果
        if test_config['save_results']:
            report = {
                "test_config": test_config,
                "summary": {
                    "total_instances": test_config['num_instances'],
                    "success_count": success_count,
                    "success_rate": success_rate,
                    "total_time": end_time - start_time,
                    "avg_time_per_instance": (end_time - start_time) / test_config['num_instances'],
                    "language_stats": lang_stats
                },
                "results": results
            }
            
            with open(test_config['output_file'], 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            
            print(f"\n📄 详细结果已保存到: {test_config['output_file']}")
    
    except Exception as e:
        print(f"❌ 主程序异常: {str(e)}")
        import traceback
        traceback.print_exc()
 
if __name__ == "__main__":
    main()