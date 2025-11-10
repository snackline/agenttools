#-- coding:UTF-8 --
# Author:lintx
# Date:2025/02/20
# 改动摘要：
# - 仅读取“代码文件”（通过 CODE_FILE_EXTS 白名单），忽略 md/json/yml/txt 等文档类
# - 上传单文件/文件夹时都按代码白名单过滤
# - 新增 UI 按钮“多Agent协作修复”，点击后调用 run_multi_agent_workflow()
# - 其余逻辑不变（缺陷检测/自动应用补丁/验证/配置/提示词等）

import re, json, time, requests, os, tempfile
from typing import List, Dict, Any,Tuple
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, QSettings, Qt, QMimeData
from PyQt5.QtWidgets import QMessageBox, QInputDialog, QFileDialog, QTextEdit, QLabel, QProgressBar, QApplication, QPushButton
from PyQt5.QtGui import QTextCursor, QDragEnterEvent, QDropEvent
from openai import OpenAI
import difflib, io, shutil, pathlib, json as _json

# 多Agent系统导入
try:
    from agents.orchestrator_agent import OrchestratorAgent
except ImportError as e:
    OrchestratorAgent = None
    print(f"[WARN] 多Agent系统未安装：{e}")

# 仅代码文件白名单（严格模式）
CODE_FILE_EXTS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.php'}

# 保障默认超时时间，避免未赋值时报错
my_timeout = 60

# 缺陷检测（静态+动态）扫描器
try:
    from analyzers.defect_scanner import DefectScanner, summarize_findings
except Exception as _e:
    DefectScanner = None
    summarize_findings = None
    print("[WARN] analyzers/defect_scanner 未找到，缺陷检测将不可用：", _e)


class DropTextEdit(QTextEdit):
    def __init__(self, parent=None, target=1):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.target = target
        self.parent_window = parent
        self.uploaded_files = []
        self._user_text = ""

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            for url in urls:
                path = url.toLocalFile()
                if os.path.isfile(path):
                    self.handle_dropped_file(path)
                elif os.path.isdir(path):
                    self.handle_dropped_folder(path)
        event.acceptProposedAction()

    def keyPressEvent(self, event):
        """捕获键盘输入 - 弹出编辑对话框"""
        from PyQt5.QtCore import Qt

        if self.uploaded_files and (
                self.toPlainText().startswith("📁 已加载") or
                self.toPlainText().startswith("✏️ 用户输入:")
        ):
            from PyQt5.QtWidgets import QInputDialog

            current_user_text = self._user_text if hasattr(self, '_user_text') else ""

            text, ok = QInputDialog.getMultiLineText(
                self.parent_window,
                f"编辑输入框 {self.target} 的文字",
                "在下方输入您的问题或文字（将与文件一起发送给AI）:\n\n提示：这些文字会和文件内容一起发送",
                current_user_text
            )

            if ok:
                self._user_text = text
                self.update_file_display()
                if self.target == 1 and hasattr(self.parent_window, 'input_size'):
                    self.parent_window.input_size()
                elif self.target == 2 and hasattr(self.parent_window, 'input_size_1'):
                    self.parent_window.input_size_1()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击编辑用户输入"""
        if self.uploaded_files:
            from PyQt5.QtWidgets import QInputDialog

            current_user_text = self._user_text if hasattr(self, '_user_text') else ""

            text, ok = QInputDialog.getMultiLineText(
                self.parent_window,
                f"编辑输入框 {self.target} 的文字",
                "在下方输入您的问题或文字（将与文件一起发送给AI）:",
                current_user_text
            )

            if ok:
                self._user_text = text
                self.update_file_display()
                if self.target == 1 and hasattr(self.parent_window, 'input_size'):
                    self.parent_window.input_size()
                elif self.target == 2 and hasattr(self.parent_window, 'input_size_1'):
                    self.parent_window.input_size_1()
        else:
            super().mouseDoubleClickEvent(event)

    def _is_code_file(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in CODE_FILE_EXTS

    def handle_dropped_file(self, file_path: str):
        """处理单个文件（仅代码文件）"""
        if not os.path.isfile(file_path):
            return
        if not self._is_code_file(file_path):
            # 非代码文件静默忽略（避免频繁弹窗）
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
            except Exception as e:
                QMessageBox.critical(self.parent_window, "错误",
                                     f"无法读取文件：{str(e)}")
                return
        except Exception as e:
            QMessageBox.critical(self.parent_window, "错误",
                                 f"读取文件失败：{str(e)}")
            return

        # 存储文件信息
        file_info = {
            'path': file_path,
            'name': os.path.basename(file_path),
            'size': len(content),
            'content': content
        }
        self.uploaded_files.append(file_info)

        # 更新显示（不显示完整内容）
        self.update_file_display()

        # 更新父窗口的计数
        if self.target == 1 and hasattr(self.parent_window, 'input_size'):
            self.parent_window.input_size()
        elif self.target == 2 and hasattr(self.parent_window, 'input_size_1'):
            self.parent_window.input_size_1()

    def handle_dropped_folder(self, folder_path: str):
        """处理文件夹（递归读取所有“代码文件”）"""
        if not os.path.isdir(folder_path):
            return

        files_found = []
        allowed_extensions = CODE_FILE_EXTS
        exclude_dirs = {'node_modules', '.git', '__pycache__', 'venv', '.venv',
                        'dist', 'build', '.idea', '.vscode'}

        for root, dirs, files in os.walk(folder_path):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in allowed_extensions:
                    files_found.append(os.path.join(root, file))

        if not files_found:
            QMessageBox.information(self.parent_window, "提示",
                                    f"在文件夹中未找到支持的“代码文件”类型")
            return

        max_files = 1000
        if len(files_found) > max_files:
            reply = QMessageBox.question(
                self.parent_window,
                "文件过多",
                f"找到 {len(files_found)} 个文件，是否只加载前 {max_files} 个？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                files_found = files_found[:max_files]
            else:
                return

        for file_path in files_found:
            self.handle_dropped_file(file_path)

        QMessageBox.information(self.parent_window, "完成",
                                f"成功加载 {len(files_found)} 个文件")

    def update_file_display(self):
        """更新文件列表显示（保留用户输入）"""
        if not self.uploaded_files:
            self.setPlaceholderText("📂 在此拖入代码文件或代码文件夹...\n或点击上传按钮选择\n\n或直接输入文字...")
            if hasattr(self, '_user_text') and self._user_text.strip():
                self.setPlainText(self._user_text)
            return

        current_text = self.toPlainText()
        if not (current_text.startswith("📁 已加载") or current_text.startswith("✏️ 用户输入:")):
            self._user_text = current_text

        lines = []
        if hasattr(self, '_user_text') and self._user_text.strip():
            lines.extend([
                "✏️ 用户输入:",
                "=" * 60,
                self._user_text,
                "=" * 60,
                ""
            ])

        lines.extend([
            f"📁 已加载 {len(self.uploaded_files)} 个文件",
            "─" * 60,
            ""
        ])

        for i, file_info in enumerate(self.uploaded_files[:10], 1):
            size_kb = file_info['size'] / 1024
            lines.append(f"{i}. {file_info['name']} ({size_kb:.1f} KB)")

        if len(self.uploaded_files) > 10:
            lines.append(f"... 还有 {len(self.uploaded_files) - 10} 个文件")

        lines.extend([
            "",
            f"💾 总计: {sum(f['size'] for f in self.uploaded_files) / 1024:.1f} KB",
            "",
            "💡 提示: 双击或按任意键可编辑文字输入"
        ])

        self.setPlainText("\n".join(lines))

    def get_user_input(self):
        """获取用户手动输入的文本 - 优化版"""
        if hasattr(self, '_user_text') and self._user_text.strip():
            return self._user_text

        current_text = self.toPlainText()
        if "✏️ 用户输入:" in current_text:
            try:
                parts = current_text.split("=" * 60)
                if len(parts) >= 3:
                    user_input = parts[1].strip()
                    self._user_text = user_input
                    return user_input
            except Exception as e:
                print(f"[DEBUG get_user_input] 提取用户输入失败: {e}")

        if "📁 已加载" not in current_text and "💡 提示:" not in current_text:
            return current_text

        return ""

    def get_all_content(self):
        """获取所有内容（用户输入 + 文件内容）- 优化版"""
        result = ""
        user_text = self.get_user_input()

        if user_text.strip():
            result += "\n" + "🔔" * 40 + "\n"
            result += "【用户的问题】\n"
            result += "🔔" * 40 + "\n"
            result += user_text
            result += "\n" + "🔔" * 40 + "\n\n"

        if self.uploaded_files:
            result += "=" * 80 + "\n"
            result += f"📦 项目文件内容（共 {len(self.uploaded_files)} 个文件）\n"
            result += "=" * 80 + "\n\n"

            for i, file_info in enumerate(self.uploaded_files, 1):
                result += f"\n{'─' * 80}\n"
                result += f"📄 文件 {i}/{len(self.uploaded_files)}: {file_info['name']}\n"
                result += f"📍 路径: {file_info['path']}\n"
                result += f"📊 大小: {file_info['size']:,} 字符 ({file_info['size'] / 1024:.1f} KB)\n"
                result += f"{'─' * 80}\n\n"
                result += file_info['content']
                result += f"\n\n{'─' * 80}\n"
                result += f"✅ 文件结束：{file_info['name']}\n"
                result += f"{'─' * 80}\n\n"

        if user_text.strip():
            result += "\n" + "🔔" * 40 + "\n"
            result += "请回答上述问题。\n"
            result += "🔔" * 40 + "\n\n"

        return result

    def clear_files(self):
        self.uploaded_files = []
        self.update_file_display()

    def clear_user_text(self):
        """仅清空用户文字，保留文件列表"""
        self._user_text = ""
        if not self.uploaded_files:
            self.clear()
        else:
            self.update_file_display()


class Worker(QThread):
    response_received = pyqtSignal(str, bool)
    error_occurred = pyqtSignal(str)

    def __init__(self, config, messages):
        super().__init__()
        self.config = config
        self.messages = messages
        self._is_running = True

    def run(self):
        try:
            if self.config.get('api_key'):
                self.call_openai_api()
            else:
                self.call_ollama()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def stop(self):
        self._is_running = False
        self.terminate()

    def call_openai_api(self):
        try:
            client = OpenAI(
                api_key=self.config["api_key"],
                base_url=self.config["api_base"],
                timeout=my_timeout
            )
            stream = client.chat.completions.create(
                model=self.config["model"],
                messages=self.messages,
                stream=True
            )
            for chunk in stream:
                if not self._is_running:
                    break
                content = chunk.choices[0].delta.content or ""
                self.response_received.emit(content, False)

            self.response_received.emit('', True)
        except Exception as e:
            self.error_occurred.emit(f"API请求失败: {str(e)}")

    def call_ollama(self):
        """调用 Ollama API（支持自动续写）"""
        api_url = self.config["api_base"]

        if "/api/generate" in api_url:
            api_url = api_url.replace("/api/generate", "/api/chat")
        elif "/api" not in api_url:
            api_url = api_url.rstrip("/") + "/api/chat"

        read_timeout = max(180, int(globals().get("my_timeout", 120)))
        connect_timeout = 10

        num_predict = int(self.config.get("num_predict", 2048))  # 默认2048

        options = {
            "num_ctx": 4096,
            "num_predict": num_predict,
            "temperature": 0.2,
            "top_p": 0.9,
        }

        if "r1" in (self.config.get("model", "") or "").lower():
            options["stop"] = ["</think>"]

        def _one_round(messages):
            """执行一轮对话"""
            done_reason = None
            data = {
                "model": self.config["model"],
                "messages": messages,
                "stream": True,
                "options": options,
                "keep_alive": "10m"
            }

            try:
                with requests.post(api_url, json=data, stream=True,
                                   timeout=(connect_timeout, read_timeout)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not self._is_running:
                            break
                        if line:
                            try:
                                chunk = json.loads(line)
                                if "message" in chunk:
                                    delta = chunk["message"].get("content", "")
                                    self.response_received.emit(delta, False)
                                if chunk.get("done", False):
                                    done_reason = chunk.get("done_reason")
                                    break
                            except Exception as e:
                                print("Ollama parse error:", e)
                                continue
            except Exception as e:
                print(f"Ollama request error: {e}")
                done_reason = "error"

            return done_reason

        done = _one_round(self.messages)

        if self._is_running and done == "length":
            self.response_received.emit("\n\n[系统提示: 回答被截断，正在自动续写...]\n\n", False)
            continuation_msg = {
                "role": "user",
                "content": "请从上一条回答中断的地方继续，补全剩余内容。确保代码块完整闭合。不要重复已输出的部分。"
            }
            extended_messages = self.messages + [continuation_msg]
            _one_round(extended_messages)

        self.response_received.emit('', True)

    def _build_prompt_from_messages(self):
        """仅在使用 generate 端点时需要；当前已用 chat 端点，保留以兼容旧逻辑"""
        prompt = ""
        for message in self.messages:
            role = message["role"]
            content = message["content"]

            if role == "system":
                prompt += f"System: {content}\n\n"
            elif role == "user":
                prompt += f"User: {content}\n\n"
            elif role == "assistant":
                prompt += f"Assistant: {content}\n\n"

        prompt += "Assistant: "
        return prompt


class EnhancedTabAI():
    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.prompts = {}
        self.thinking_start = None
        self.configs = {}
        self.messages = []
        self._ai_reply_buffer = ""

        # 开关：回答结束后是否自动清空输入文字（保留文件）
        self.auto_clear_input = True
        # 默认不回写
        self.enable_auto_writeback = False

        self.replace_input_widgets()
        self.init_ui()
        self.load_prompts()
        self.load_configs()
        self._last_local_scan_result = {}  # 本地扫描结果

    def replace_input_widgets(self):
        input1_geo = self.ui.input_edit.geometry()
        input2_geo = self.ui.input_edit_1.geometry()
        input1_parent = self.ui.input_edit.parent()
        input2_parent = self.ui.input_edit_1.parent()

        input1_frame_shape = self.ui.input_edit.frameShape()
        input1_frame_shadow = self.ui.input_edit.frameShadow()
        input2_frame_shape = self.ui.input_edit_1.frameShape()
        input2_frame_shadow = self.ui.input_edit_1.frameShadow()

        self.ui.input_edit.deleteLater()
        self.ui.input_edit_1.deleteLater()

        self.ui.input_edit = DropTextEdit(self.ui, target=1)
        self.ui.input_edit.setParent(input1_parent)
        self.ui.input_edit.setGeometry(input1_geo)
        self.ui.input_edit.setObjectName("input_edit")
        self.ui.input_edit.setFrameShape(input1_frame_shape)
        self.ui.input_edit.setFrameShadow(input1_frame_shadow)
        self.ui.input_edit.setUndoRedoEnabled(True)
        self.ui.input_edit.setAcceptRichText(False)
        self.ui.input_edit.show()

        self.ui.input_edit_1 = DropTextEdit(self.ui, target=2)
        self.ui.input_edit_1.setParent(input2_parent)
        self.ui.input_edit_1.setGeometry(input2_geo)
        self.ui.input_edit_1.setObjectName("input_edit_1")
        self.ui.input_edit_1.setFrameShape(input2_frame_shape)
        self.ui.input_edit_1.setFrameShadow(input2_frame_shadow)
        self.ui.input_edit_1.setUndoRedoEnabled(True)
        self.ui.input_edit_1.setAcceptRichText(False)
        self.ui.input_edit_1.show()

    def init_ui(self):
        self.is_running = False
        self.reposition_upload_buttons()
        self.setup_styles()
        self.setup_connections()
        self.setup_status_bar()
        self.set_placeholder_texts()

        # 动态创建"多Agent协作修复"按钮，放到状态栏右侧（右下角）
        try:
            if not hasattr(self.ui, 'multi_agent_btn') or self.ui.multi_agent_btn is None:
                self.ui.multi_agent_btn = QPushButton("🤖 多Agent协作修复")
                self.ui.multi_agent_btn.setObjectName("multi_agent_btn")
                # 放到状态栏右侧（永久控件区域）
                if hasattr(self.ui, 'statusBar'):
                    self.ui.statusBar().addPermanentWidget(self.ui.multi_agent_btn)
                else:
                    # 兜底：放到 send_btn 左侧
                    parent = self.ui.send_btn.parent()
                    self.ui.multi_agent_btn.setParent(parent)
                    sb_geo = self.ui.send_btn.geometry()
                    self.ui.multi_agent_btn.setGeometry(sb_geo.x() - 140, sb_geo.y(), 130, sb_geo.height())
                    self.ui.multi_agent_btn.show()
        except Exception as e:
            print(f"[WARN] 创建多Agent按钮失败：{e}")

        # 绑定点击事件
        try:
            self.ui.multi_agent_btn.clicked.connect(self.run_multi_agent_workflow)
        except Exception:
            pass

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)

    def reposition_upload_buttons(self):
        try:
            input1_rect = self.ui.input_edit.geometry()
            input2_rect = self.ui.input_edit_1.geometry()

            input1_parent = self.ui.input_edit.parent()
            input2_parent = self.ui.input_edit_1.parent()

            if hasattr(self.ui, 'upload_btn1'):
                self.ui.upload_btn1.setParent(input1_parent)
                btn1_x = input1_rect.x() + input1_rect.width() - 75
                btn1_y = input1_rect.y() + input1_rect.height() - 33
                self.ui.upload_btn1.setGeometry(btn1_x, btn1_y, 70, 28)
                self.ui.upload_btn1.setText("📁 上传")
                self.ui.upload_btn1.setToolTip("左键上传文件/文件夹\n右键清空已上传文件")
                self.ui.upload_btn1.raise_()
                self.ui.upload_btn1.show()

            if hasattr(self.ui, 'upload_btn2'):
                self.ui.upload_btn2.setParent(input2_parent)
                btn2_x = input2_rect.x() + input2_rect.width() - 75
                btn2_y = input2_rect.y() + input2_rect.height() - 33
                self.ui.upload_btn2.setGeometry(btn2_x, btn2_y, 70, 28)
                self.ui.upload_btn2.setText("📁 上传")
                self.ui.upload_btn2.setToolTip("左键上传文件/文件夹\n右键清空已上传文件")
                self.ui.upload_btn2.raise_()
                self.ui.upload_btn2.show()

        except Exception as e:
            import traceback
            traceback.print_exc()

    def _truncate_for_ctx(self, text: str, max_chars: int = 12000) -> str:
        """为避免超出上下文（num_ctx=4096），对发送给模型的文本做一次保守字符级裁剪"""
        if text and len(text) > max_chars:
            return text[:max_chars] + "\n\n[提示] 为满足上下文限制，已对上下文进行截断。"
        return text

    def _prune_context(self, max_chars: int = 20000, keep_last: int = 6):
        """在每轮结束后裁剪上下文：保留system + 最近若干条消息，防止越聊越长导致超时/截断"""
        if not self.messages:
            return
        systems = [m for m in self.messages if m.get("role") == "system"]
        others = [m for m in self.messages if m.get("role") != "system"]
        kept = others[-keep_last:] if len(others) > keep_last else others
        new_msgs = systems + kept
        def total_len(ms):
            return sum(len(m.get("content", "")) for m in ms)
        while total_len(new_msgs) > max_chars and len(kept) > 2:
            kept = kept[1:]
            new_msgs = systems + kept
        self.messages = new_msgs

    def setup_styles(self):
        style = """
        QMainWindow {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34495e, stop:1 #2c3e50);
        }
        QStatusBar {
            background: rgba(0, 0, 0, 0.3);
            color: white;
            border: none;
            font-size: 12px;
        }
        QStatusBar QLabel {
            color: white;
            background: transparent;
        }
        QTextEdit, QPlainTextEdit {
            background: #ffffff;
            border: 1px solid #3498db;
            border-radius: 8px;
            padding: 8px;
            font-size: 14px;
            font-family: "Arial", sans-serif;
        }
        QPushButton {
            background: #2980b9;
            border: none;
            border-radius: 8px;
            color: white;
            padding: 8px 14px;
            font-size: 14px;
        }
        QPushButton:hover {
            background: #3498db;
        }
        #send_btn {
            background: #27ae60;
            font-size: 14px;
            min-height: 25px;
            margin: 10px 0px;
            border-radius: 8px;
        }
        #send_btn:hover { background: #2ecc71; }
        #upload_btn1, #upload_btn2 {
            background: #9b59b6;
            font-size: 12px;
            border: 1px solid #8e44ad;
            border-radius: 6px;
            padding: 6px 12px;
        }
        #upload_btn1:hover, #upload_btn2:hover { background: #af7ac5; }
        QGroupBox {
            background: white;
            border: 1px solid #bdc3c7;
            border-radius: 8px;
            margin-top: 10px;
            padding: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
            color: #3498db;
            font-weight: bold;
        }
        """
        if hasattr(self, 'ui') and self.ui:
            self.ui.setStyleSheet(style)

    def setup_connections(self):
        self.ui.send_btn.clicked.connect(self.toggle_ai_process)
        self.ui.prompt_combo.currentTextChanged.connect(self.update_prompt)
        self.ui.prompt_combo_1.currentTextChanged.connect(self.update_prompt_1)
        self.ui.refresh_btn.clicked.connect(self.load_prompts)
        self.ui.new_btn.clicked.connect(self.new_prompt)
        self.ui.delete_btn.clicked.connect(self.delete_prompt)
        self.ui.save_prompt_btn.clicked.connect(self.save_prompt)
        self.ui.prompt_edit.textChanged.connect(self.hide_input)
        self.ui.input_edit.textChanged.connect(self.input_size)
        self.ui.input_edit_1.textChanged.connect(self.input_size_1)
        self.ui.config_combo.currentTextChanged.connect(self.update_config)
        self.ui.config_combo_1.currentTextChanged.connect(self.update_config_1)
        self.ui.new_config_btn.clicked.connect(self.new_config)
        self.ui.save_config_btn.clicked.connect(self.save_config)
        self.ui.del_config_btn.clicked.connect(self.del_config)
        self.ui.refresh_btn_2.clicked.connect(self.refresh_config)
        self.ui.config_combo.currentIndexChanged.connect(self.load_config)

        if hasattr(self.ui, 'clear_ctx_btn'):
            self.ui.clear_ctx_btn.clicked.connect(self.clear_context)

        if hasattr(self.ui, 'upload_btn1'):
            self.ui.upload_btn1.clicked.connect(lambda: self.upload_file(target=1))
            self.ui.upload_btn1.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.upload_btn1.customContextMenuRequested.connect(
                lambda: self.clear_uploaded_files(target=1)
            )

        if hasattr(self.ui, 'upload_btn2'):
            self.ui.upload_btn2.clicked.connect(lambda: self.upload_file(target=2))
            self.ui.upload_btn2.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.upload_btn2.customContextMenuRequested.connect(
                lambda: self.clear_uploaded_files(target=2)
            )

        # 绑定“多Agent协作修复”按钮（若存在）
        if hasattr(self.ui, 'multi_agent_btn'):
            try:
                self.ui.multi_agent_btn.clicked.connect(self.run_multi_agent_workflow)
            except Exception:
                pass

    def clear_uploaded_files(self, target=1):
        widget = self.ui.input_edit if target == 1 else self.ui.input_edit_1

        if not hasattr(widget, 'uploaded_files') or not widget.uploaded_files:
            QMessageBox.information(self.ui, "提示", f"输入框{target}没有已上传的文件")
            return

        reply = QMessageBox.question(
            self.ui,
            "确认清空",
            f"确定要清空输入框 {target} 的所有已上传文件吗？\n当前有 {len(widget.uploaded_files)} 个文件",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if hasattr(widget, 'clear_files'):
                widget.clear_files()
            else:
                widget.uploaded_files = []
                widget.clear()

            if target == 1:
                self.input_size()
            else:
                self.input_size_1()

            QMessageBox.information(self.ui, "提示", "已清空所有文件")

    def setup_status_bar(self):
        self.status_label = QLabel("🟢 就绪 | 模型: 未选择 | 上下文: 0 条消息")
        if hasattr(self.ui, 'statusBar'):
            self.ui.statusBar().addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setVisible(False)
        if hasattr(self.ui, 'statusBar'):
            self.ui.statusBar().addPermanentWidget(self.progress_bar)

    def set_placeholder_texts(self):
        if hasattr(self.ui, 'input_edit'):
            self.ui.input_edit.setPlaceholderText("在此输入您的内容...\n点击上传按钮进行上传")
        if hasattr(self.ui, 'input_edit_1'):
            self.ui.input_edit_1.setPlaceholderText("在此输入补充内容或第二个输入...\n点击上传按钮进行上传")
        if hasattr(self.ui, 'prompt_edit'):
            self.ui.prompt_edit.setPlaceholderText("提示词模板区域，可使用 [输入1] 和 [输入2] 作为占位符")
        if hasattr(self.ui, 'output_area'):
            self.ui.output_area.setPlaceholderText("AI回复将显示在这里...\n支持多轮对话，点击AI分析和处理可开始提问")

    def upload_file(self, target=1):
        reply = QMessageBox.question(
            self.ui,
            "选择上传类型",
            "请选择：\n\n是 = 上传文件\n否 = 上传文件夹",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )

        if reply == QMessageBox.Cancel:
            return
        elif reply == QMessageBox.Yes:
            file_path, _ = QFileDialog.getOpenFileName(
                self.ui,
                "选择文件",
                "",
                "代码文件 (*.py *.js *.ts *.java *.cpp *.c *.h *.cs *.go *.rs *.php);;所有文件 (*)"
            )
            if file_path:
                target_widget = self.ui.input_edit if target == 1 else self.ui.input_edit_1
                target_widget.handle_dropped_file(file_path)
        else:
            folder_path = QFileDialog.getExistingDirectory(
                self.ui,
                "选择项目文件夹",
                ""
            )
            if folder_path:
                target_widget = self.ui.input_edit if target == 1 else self.ui.input_edit_1
                target_widget.handle_dropped_folder(folder_path)

    def clear_context(self):
        self.messages = []
        self.ui.output_area.append("=== 上下文已清空 ===")
        self.ui.output_area.moveCursor(QTextCursor.End)
        self.update_status_bar()

    def input_size(self):
        if hasattr(self.ui.input_edit, 'uploaded_files'):
            file_count = len(self.ui.input_edit.uploaded_files)
            total_size = sum(f['size'] for f in self.ui.input_edit.uploaded_files)
            self.ui.label_input1.setText(
                f'[输入1] 📁 {file_count} 个文件 | {total_size} 字符'
            )
        else:
            size = len(self.ui.input_edit.toPlainText())
            self.ui.label_input1.setText(f'[输入1] {size} 字符')

    def input_size_1(self):
        if hasattr(self.ui.input_edit_1, 'uploaded_files'):
            file_count = len(self.ui.input_edit_1.uploaded_files)
            total_size = sum(f['size'] for f in self.ui.input_edit_1.uploaded_files)
            self.ui.label_input2.setText(
                f'[输入2] 📁 {file_count} 个文件 | {total_size} 字符'
            )
        else:
            size = len(self.ui.input_edit_1.toPlainText())
            self.ui.label_input2.setText(f'[输入2] {size} 字符')

    def toggle_ai_process(self):
        if self.is_running:
            self.handle_interrupt()
        else:
            self.on_send()

    def hide_input(self):
        self.ui.input_edit.setEnabled(True)
        self.ui.input_edit_1.setEnabled(True)

    def handle_interrupt(self):
        if hasattr(self, 'worker'):
            self.worker.stop()
        self.cleanup_after_interrupt()
        self.ui.output_area.append("=== 用户中止 ===")
        self.update_status_bar()

    def cleanup_after_interrupt(self):
        self.timer.stop()
        self.ui.send_btn.setText("AI分析和处理")
        self.ui.send_btn.setStyleSheet("")
        self.is_running = False
        self.thinking_start = None
        self.progress_bar.setVisible(False)

    def update_time(self):
        if self.thinking_start:
            elapsed = time.time() - self.thinking_start
            self.ui.send_btn.setText(f"中止（{elapsed:.2f}s）")
            progress = min(int((elapsed % 3) * 33), 100)
            self.progress_bar.setValue(progress)

    def handle_error(self, error_msg):
        self.timer.stop()
        self.ui.output_area.append(f"\n[错误] {error_msg}")
        self.ui.send_btn.setEnabled(True)
        self.thinking_start = None
        self.ui.send_btn.setText("AI分析和处理")
        self.ui.send_btn.setStyleSheet("")
        self.is_running = False
        self.progress_bar.setVisible(False)
        self.update_status_bar()

    def _clear_user_inputs(self):
        """对话结束后清空两侧的用户文字（保留文件），并刷新计数"""
        if hasattr(self.ui, "input_edit") and hasattr(self.ui.input_edit, "clear_user_text"):
            self.ui.input_edit.clear_user_text()
        elif hasattr(self.ui, "input_edit"):
            self.ui.input_edit.clear()
        if hasattr(self.ui, "input_edit_1") and hasattr(self.ui.input_edit_1, "clear_user_text"):
            self.ui.input_edit_1.clear_user_text()
        elif hasattr(self.ui, "input_edit_1"):
            self.ui.input_edit_1.clear()
        if hasattr(self, "input_size"):
            self.input_size()
        if hasattr(self, "input_size_1"):
            self.input_size_1()

    def update_response(self, delta, finished):
        try:
            if not self.is_running:
                return
            processed = delta.replace('<think>', '[思考]').replace('</think>', '[/思考]')
            self.ui.output_area.moveCursor(QTextCursor.End)
            self.ui.output_area.insertPlainText(processed)

            if finished:
                full_text = getattr(self, "_ai_reply_buffer", "")
                if full_text:
                    self.messages.append({"role": "assistant", "content": full_text})
                self._ai_reply_buffer = ""

                if getattr(self, "auto_clear_input", True):
                    self._clear_user_inputs()
                self._prune_context(max_chars=20000, keep_last=6)

                self.cleanup_after_interrupt()
                self.ui.output_area.append("\n=== 回答结束 ===")
                self.ui.output_area.moveCursor(QTextCursor.End)
                self.update_status_bar()

                try:
                    if full_text:
                        self.try_auto_apply_and_verify(full_text)
                except Exception as _e:
                    self.ui.output_area.append(f"⚠️ 自动应用与验证失败：{_e}")
        except Exception as e:
            import traceback
            traceback.print_exc()

    # ========= 收集文件 + 运行缺陷检测 ==========
    def _collect_uploaded_files(self) -> List[Dict[str, Any]]:
        files = []
        for w in [getattr(self.ui, "input_edit", None), getattr(self.ui, "input_edit_1", None)]:
            if not w:
                continue
            arr = getattr(w, "uploaded_files", []) or []
            for f in arr:
                files.append({
                    "path": f.get("path"),
                    "name": f.get("name"),
                    "content": f.get("content", ""),
                    "size": f.get("size", 0),
                })
        return files

    def _run_local_defect_scan(self) -> Dict[str, Any]:
        if DefectScanner is None:
            self.ui.output_area.append("⚠️ 未找到 analyzers/defect_scanner.py，跳过缺陷检测。")
            self._last_local_scan_result = {}
            return {}

        files = self._collect_uploaded_files()
        if not files:
            self.ui.output_area.append("ℹ️ 未检测到已上传文件，跳过缺陷检测。")
            self._last_local_scan_result = {}
            return {}

        self.ui.output_area.append("🔍 正在进行本地缺陷检测（静态 + 动态/轻量 + 外部工具）...")
        self.ui.output_area.repaint()
        QApplication.processEvents()

        try:
            scanner = DefectScanner(files)
            result = scanner.scan(enable_external=True, enable_dynamic=True, dynamic_timeout=10)
            self._last_local_scan_result = result
            builtin_cnt = len(result.get("static_builtin", []))
            self.ui.output_area.append(f"✅ 缺陷检测完成。静态内置结果：{builtin_cnt} 条。")
            dyn = result.get("dynamic", {})

            if dyn:
                comp_err = len(dyn.get("py_compile", []) or [])
                self.ui.output_area.append(f"   - 动态编译错误：{comp_err} 条。")
                if dyn.get("pytest", {}).get("skipped"):
                    self.ui.output_area.append(f"   - pytest: 跳过（{dyn.get('pytest', {}).get('reason')})")
                else:
                    self.ui.output_area.append(f"   - pytest exit: {dyn.get('pytest', {}).get('exit_code')}")
            return result
        except Exception as e:
            self.ui.output_area.append(f"❌ 缺陷检测失败：{e}")
            self._last_local_scan_result = {}
            return {}

    # ========= 发送前先本地扫描，给模型喂摘要 ==========
    def on_send(self):
        """发送消息给AI - 接入缺陷检测（先扫再问）"""
        global my_timeout
        my_timeout = int(self.ui.timeout_input.text() or "60")

        if hasattr(self.ui.input_edit, 'uploaded_files') and self.ui.input_edit.uploaded_files:
            user_input = self.ui.input_edit.get_all_content()
        else:
            user_input = self.ui.input_edit.toPlainText().strip()

        if hasattr(self.ui.input_edit_1, 'uploaded_files') and self.ui.input_edit_1.uploaded_files:
            user_input_1 = self.ui.input_edit_1.get_all_content()
        else:
            user_input_1 = self.ui.input_edit_1.toPlainText().strip()

        if not user_input and self.ui.input_edit.isEnabled():
            QMessageBox.critical(self.ui, "错误", "输入框1未输入数据或上传文件")
            return

        scan_result = self._run_local_defect_scan()
        self._last_scan_dynamic = (scan_result or {}).get("dynamic", {})
        ai_context = ""
        if scan_result and summarize_findings:
            ai_context = summarize_findings(scan_result, top_k=20)

        prompt_template = self.ui.prompt_edit.toPlainText().strip() or "[输入1]\n\n[输入2]"
        if ai_context:
            final_template = (
                "你是代码缺陷修复助手。下面是本地静态/动态检测的缺陷摘要，请逐条给出修复建议与示例补丁（统一 diff 或带文件名的完整代码块）。\n\n"
                "【缺陷摘要】\n[缺陷]\n\n"
                "【用户补充问题/期望】\n[用户]\n"
            )
            user_msg = (
                final_template
                .replace("[缺陷]", ai_context)
                .replace("[用户]", (self.ui.input_edit.get_user_input() if hasattr(self.ui.input_edit, "get_user_input") else user_input) + "\n" + user_input_1)
            )
        else:
            user_msg = prompt_template.replace("[输入1]", user_input).replace("[输入2]", user_input_1)

        if self.is_running:
            self.handle_interrupt()
            return

        self.is_running = True
        self.ui.send_btn.setText("中止（0.00s）")
        self.ui.send_btn.setStyleSheet("background-color: #e74c3c;")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        has_system_msg = any(msg.get("role") == "system" for msg in self.messages)
        if not has_system_msg:
            self.messages.append({
                "role": "system",
                "content": (
                    "你是专业的缺陷修复助手。若提供了缺陷摘要，请逐条给出修复建议/示例补丁；"
                    "若涉及安全问题（命令注入、反序列化、弱哈希、SQL 注入等）需优先处理并附带修复代码。"
                )
            })
        user_msg = self._truncate_for_ctx(user_msg, max_chars=12000)
        self.messages.append({"role": "user", "content": user_msg})

        self.ui.output_area.clear()
        self.thinking_start = time.time()
        self.timer.start(100)

        self.config = {
            "name": self.ui.config_combo.currentText(),
            "api_base": self.ui.conf_api_base.text(),
            "api_key": self.ui.conf_api_key.text(),
            "model": self.ui.conf_model.text()
        }

        self.worker = Worker(self.config, self.messages.copy())
        self.worker.response_received.connect(self.update_response)
        self.worker.error_occurred.connect(self.handle_error)
        self.worker.start()

        prompt_combo = self.ui.prompt_combo_1.currentText()
        model_combo = self.ui.config_combo.currentText()
        c1 = len(getattr(self.ui.input_edit, 'uploaded_files', []) or [])
        c2 = len(getattr(self.ui.input_edit_1, 'uploaded_files', []) or [])

        self.ui.output_area.append("=" * 80)
        self.ui.output_area.append("🚀 开始分析")
        self.ui.output_area.append("=" * 80)
        self.ui.output_area.append(f"⏱️  超时设置: {my_timeout} 秒")
        self.ui.output_area.append(f"💡 提示词模板: {prompt_combo}")
        self.ui.output_area.append(f"🤖 AI模型: {model_combo}")
        self.ui.output_area.append(f"📁 输入框1: {c1} 个文件")
        self.ui.output_area.append(f"📁 输入框2: {c2} 个文件")
        if scan_result:
            self.ui.output_area.append("📑 已生成本地缺陷摘要，模型将基于摘要给出修复建议。")
        self.ui.output_area.append("=" * 80 + "\n")
        self.update_status_bar()

    def update_status_bar(self):
        model_name = self.ui.config_combo.currentText() or "未选择"
        context_count = len(self.messages)
        status_icon = "🟢" if not self.is_running else "🟡"
        status_text = "就绪" if not self.is_running else "思考中"

        self.status_label.setText(
            f"{status_icon} {status_text} | 模型: {model_name} | "
            f"上下文: {context_count} 条消息"
        )

    # --- 提示词与配置管理保持不变 ---
    def load_prompts(self):
        try:
            with open("config/提示词.md", "r", encoding="utf-8") as f:
                content = f.read()
            pattern = r"### (.*?)```(.*?)```"
            matches = re.findall(pattern, content, re.DOTALL)
            self.prompts = {title.strip(): prompt.strip() for title, prompt in matches}
            self.ui.prompt_combo.clear()
            self.ui.prompt_combo.addItems(self.prompts.keys())
            if self.prompts:
                self.ui.prompt_combo.setCurrentIndex(0)
            self.ui.prompt_combo_1.clear()
            self.ui.prompt_combo_1.addItems(self.prompts.keys())
            if self.prompts:
                self.ui.prompt_combo_1.setCurrentIndex(0)
        except Exception as e:
            QMessageBox.critical(self.ui, "错误", f"加载提示词失败: {str(e)}")

    def update_prompt(self):
        title = self.ui.prompt_combo.currentText()
        self.ui.prompt_edit.setPlainText(self.prompts.get(title, ""))
        self.ui.prompt_combo_1.setCurrentText(title)

    def update_prompt_1(self):
        title = self.ui.prompt_combo_1.currentText()
        self.ui.prompt_edit.setPlainText(self.prompts.get(title, ""))
        self.ui.prompt_combo.setCurrentText(title)

    # -------------------- 指标（保留更详细版本，去重） --------------------
    def _persist_metrics(self, before: Dict[str, Any], after: Dict[str, Any], extra: Dict[str, Any] = None):
        """
        完整的量化评估指标
        """
        before_static = before.get("static_builtin", []) if isinstance(before, dict) else []
        after_static = after.get("static_builtin", []) if isinstance(after.get("dynamic"), dict) else []

        static_metrics = {
            "before_total": len(before_static),
            "before_high": len([f for f in before_static if f.get("severity") == "HIGH"]),
            "before_medium": len([f for f in before_static if f.get("severity") == "MEDIUM"]),
            "before_low": len([f for f in before_static if f.get("severity") == "LOW"]),
        }

        before_py_compile = len(before.get("py_compile", [])) if isinstance(before, dict) else 0
        after_dyn = after.get("dynamic", {}) if isinstance(after, dict) else {}
        after_py_compile = len(after_dyn.get("py_compile", []))
        before_pytest = before.get("pytest", {}) if isinstance(before, dict) else {}
        after_pytest = after_dyn.get("pytest", {})

        dynamic_metrics = {
            "py_compile_before": before_py_compile,
            "py_compile_after": after_py_compile,
            "py_compile_fixed": before_py_compile - after_py_compile,
            "pytest_before_exit": before_pytest.get("exit_code", -1),
            "pytest_after_exit": after_pytest.get("exit_code", -1),
            "pytest_before_failed": before_pytest.get("failed_count", 0),
            "pytest_after_failed": after_pytest.get("failed_count", 0),
        }

        total_issues = static_metrics["before_total"] + dynamic_metrics["py_compile_before"]
        fixed_issues = dynamic_metrics["py_compile_fixed"]
        success_rate = (fixed_issues / total_issues * 100) if total_issues > 0 else 0

        data = {
            "timestamp": int(time.time()),
            "static_metrics": static_metrics,
            "dynamic_metrics": dynamic_metrics,
            "success_rate": round(success_rate, 2),
            "extra": extra or {},
            "before": before or {},
            "after": after or {}
        }

        os.makedirs("runs", exist_ok=True)
        fp = os.path.join("runs", f"metrics_{data['timestamp']}.json")
        with open(fp, "w", encoding="utf-8") as w:
            w.write(_json.dumps(data, ensure_ascii=False, indent=2))

        self.ui.output_area.append("\n" + "=" * 80)
        self.ui.output_area.append("📊 量化评估结果")
        self.ui.output_area.append("=" * 80)
        self.ui.output_area.append(f"📈 修复成功率: {success_rate:.1f}%")
        self.ui.output_area.append(
            f"🐛 编译错误: {before_py_compile} → {after_py_compile} (修复 {dynamic_metrics['py_compile_fixed']}个)")
        self.ui.output_area.append(
            f"🧪 pytest: exit_code {dynamic_metrics['pytest_before_exit']} → {dynamic_metrics['pytest_after_exit']}")
        self.ui.output_area.append(f"💾 详细数据已保存: {fp}")
        self.ui.output_area.append("=" * 80)

    # -------------------- 补丁解析/应用（修复与增强） --------------------
    def _parse_unified_diffs(self, text: str) -> List[Tuple[str, str]]:
        """
        从 AI 回答中提取 unified diff 块（更鲁棒）
        支持：
        - ```diff / ```patch（大小写/前后空格/CRLF）
        - 裸的 --- a/file +++ b/file + @@
        - diff --git a/file b/file
        返回：[(推断的文件名或占位, diff文本), ...]
        """
        results: List[Tuple[str, str]] = []

        # 1) fenced diff/patch（大小写/空格/CRLF）
        for m in re.finditer(r"```(?:\s*)(diff|patch)(?:\s*)\r?\n(.*?)```", text, re.S | re.IGNORECASE):
            diff_content = m.group(2).replace("\r\n", "\n")
            # 提取第一个文件名用于展示（应用时走整段）
            file_match = re.search(r"(?:^|\n)(?:---|\+\+\+)\s+[ab]/([^\s\n]+)", diff_content)
            filename = file_match.group(1) if file_match else "<patch>"
            results.append((filename, diff_content))

        # 2) 裸 unified diff（---/+++ 与 @@）
        candidates = re.findall(
            r"(?:(?:^|\n)---\s[^\n]+\r?\n\+\+\+\s[^\n]+\r?\n(?:@@.*\r?\n)+(?:.*\r?\n)*?)(?=\n{2,}|\Z)",
            text, re.S
        )
        for c in candidates:
            diff_block = c.replace("\r\n", "\n").strip()
            if "@@" not in diff_block:
                continue
            file_match = re.search(r"(?:---|\+\+\+)\s+[ab]/([^\s\n]+)", diff_block)
            filename = file_match.group(1) if file_match else "<patch>"
            results.append((filename, diff_block))

        # 3) diff --git
        for m in re.finditer(r"diff --git a/([^\s]+) b/([^\s]+)\n(.*?)(?=\ndiff --git|\Z)", text, re.S):
            filename = m.group(2)
            diff_content = ("diff --git a/%s b/%s\n%s" % (m.group(1), m.group(2), m.group(3))).replace("\r\n", "\n")
            results.append((filename, diff_content))

        return results

    def _apply_unified_diff_patchset(self, work_dir: str, patch_text: str) -> bool:
        """
        一次性应用整段 unified diff（支持无 diff --git，仅有 ---/+++ 与 @@）。
        依赖 patch-ng：pip install patch-ng
        """
        try:
            import patch_ng as patch
        except Exception:
            self.ui.output_area.append("⚠️ 未安装 patch-ng，无法自动应用 unified diff。请先 pip install patch-ng")
            return False

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.diff', delete=False, encoding='utf-8', newline="\n") as f:
                f.write(patch_text)
                diff_file = f.name
            try:
                patchset = patch.fromfile(diff_file)
                if not patchset:
                    return False
                ok = patchset.apply(root=work_dir, strip=1)  # 去掉 a/ b/
                if not ok:
                    ok = patchset.apply(root=work_dir, strip=0)
                return bool(ok)
            finally:
                try:
                    os.unlink(diff_file)
                except:
                    pass
        except Exception as e:
            self.ui.output_area.append(f"⚠️ 应用 unified diff 失败：{e}")
            return False

    def _apply_unified_diff(self, work_dir: str, filename: str, diff_text: str) -> bool:
        """
        使用 patch-ng 应用 unified diff；失败时不再手动单文件解析（容易错位），统一回退到整段应用
        """
        return self._apply_unified_diff_patchset(work_dir, diff_text)

    def _parse_inline_code_blocks(self, text: str) -> List[Tuple[str, str]]:
        """
        解析 AI 回答中的 Python 代码块（严格）：
        - 仅接受 ```python 相对路径.py\n<代码>``` 形式
        - 拒绝 diff/patch 语言、拒绝 '--- ' '+++ ' 伪文件名、拒绝 a/ b/ 前缀
        - 保留相对路径（不做 basename），以便在工作区正确定位
        """
        results: List[Tuple[str, str]] = []
        pattern = re.compile(r"```(\w+)?\s*([^\n`]+)\s*\r?\n(.*?)```", re.S | re.IGNORECASE)
        for m in pattern.finditer(text):
            lang = (m.group(1) or "").strip().lower()
            fname = (m.group(2) or "").strip()
            code = m.group(3)
            if not fname or not code:
                continue
            if lang in ("diff", "patch"):
                continue
            if not fname.endswith(".py"):
                continue
            if fname.startswith("--- ") or fname.startswith("+++ "):
                continue
            low = fname.lower()
            if low.startswith("a/") or low.startswith("b/") or " a/" in fname or " b/" in fname:
                continue
            if any(ch in fname for ch in ("\r", "\n", "\t")):
                continue
            if not any(kw in code for kw in ("def ", "class ", "import ", "from ")):
                continue
            results.append((os.path.normpath(fname), code))
        return results

    def _apply_inline_code_blocks(self, work_dir: str, blocks: List[Tuple[str, str]]) -> bool:
        """
        将完整的代码块写入文件（保持相对路径），至少写入一个文件返回 True
        """
        try:
            written = 0
            for rel_path, content in blocks:
                target = os.path.abspath(os.path.join(work_dir, rel_path))
                if not target.startswith(os.path.abspath(work_dir) + os.sep):
                    self.ui.output_area.append(f"拒绝越界写入: {rel_path}")
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, 'w', encoding='utf-8', newline='\n') as f:
                    f.write(content)
                    if not content.endswith('\n'):
                        f.write('\n')
                self.ui.output_area.append(f"  ✅ 已写入: {rel_path} ({len(content)} 字节)")
                written += 1
            return written > 0
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.ui.output_area.append(f"  ❌ 写入失败: {e}")
            return False

    def _workspace_from_uploaded(self) -> str:
        """将已上传文件写入临时工作区，避免直接改用户原文件。"""
        files = self._collect_uploaded_files()
        tmp = tempfile.mkdtemp(prefix="agentfix_")
        for f in files:
            rel = f.get("path") or f.get("name") or "file.py"
            rel = os.path.basename(rel)
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="\n") as w:
                w.write(f.get("content", ""))
        return tmp

    def _diff_changed_files(self, work_dir: str) -> List[str]:
        """
        比对工作区与上传原文件内容，返回实际发生变化的文件（按文件名匹配）
        """
        changed = []
        original_map: Dict[str, str] = {}
        for w in [getattr(self.ui, "input_edit", None), getattr(self.ui, "input_edit_1", None)]:
            if not w:
                continue
            for f in getattr(w, "uploaded_files", []) or []:
                original_map[os.path.basename(f.get("path") or f.get("name") or "")] = f.get("content", "")

        for root, _, files in os.walk(work_dir):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as r:
                        new_content = r.read()
                except Exception:
                    continue
                old_content = original_map.get(fn)
                if old_content is not None and old_content != new_content:
                    rel = os.path.relpath(fp, work_dir)
                    changed.append(rel)
        return changed

    def _write_back_from_workspace(self, work_dir: str, applied_files: List[str]):
        """
        将工作区里修改的文件回写到用户原始文件（按文件名匹配，保守策略）
        """
        original_map: Dict[str, str] = {}
        for w in [getattr(self.ui, "input_edit", None), getattr(self.ui, "input_edit_1", None)]:
            if not w:
                continue
            for f in getattr(w, "uploaded_files", []) or []:
                original_map[os.path.basename(f.get("path") or f.get("name") or "")] = f.get("path") or ""

        for rel in applied_files:
            name = os.path.basename(rel)
            src = os.path.join(work_dir, rel)
            dst = original_map.get(name)
            if not dst:
                self.ui.output_area.append(f"跳过未映射文件：{rel}")
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    def _verify_workspace(self, work_dir: str, timeout_sec: int = 10) -> Dict[str, Any]:
        """
        复用本地动态验证逻辑：py_compile + pytest
        """
        try:
            from analyzers.defect_scanner import DefectScanner
            files = []
            for root, _, fs in os.walk(work_dir):
                for fn in fs:
                    if fn.endswith(".py"):
                        fp = os.path.join(root, fn)
                        with open(fp, "r", encoding="utf-8", errors="ignore") as r:
                            files.append({"path": fp, "name": os.path.basename(fp), "content": r.read(), "size": 0})
            ds = DefectScanner(files)
            return {"dynamic": ds.run_dynamic_light(work_dir, timeout_sec)}
        except Exception as e:
            return {"error": str(e)}

    def _show_verification_result(self, after: Dict[str, Any]):
        """显示验证结果摘要"""
        self.ui.output_area.append("\n" + "=" * 80)
        self.ui.output_area.append("✅ 验证完成")
        self.ui.output_area.append("=" * 80)

        dyn = after.get("dynamic", {})

        py_compile_errors = dyn.get("py_compile", [])
        if py_compile_errors:
            self.ui.output_area.append(f"  ⚠️ 仍有 {len(py_compile_errors)} 个编译错误")
            for err in py_compile_errors[:3]:
                self.ui.output_area.append(f"    - {os.path.basename(err.get('file', ''))}")
                self.ui.output_area.append(f"      {err.get('error', '')[:150]}")
        else:
            self.ui.output_area.append(f"  ✅ py_compile: 全部通过")

        pytest_result = dyn.get("pytest", {})
        if not pytest_result.get("skipped"):
            exit_code = pytest_result.get("exit_code", -1)
            passed = pytest_result.get("passed_count", 0)
            failed = pytest_result.get("failed_count", 0)

            if exit_code == 0:
                self.ui.output_area.append(f"  ✅ pytest: 全部通过 ({passed} 个测试)")
            else:
                self.ui.output_area.append(f"  ❌ pytest: {failed} 个失败, {passed} 个通过")
                failed_tests = pytest_result.get("failed_tests", [])
                if failed_tests:
                    self.ui.output_area.append(f"    失败用例: {', '.join(failed_tests[:3])}")
        else:
            self.ui.output_area.append(f"  ℹ️ pytest: 跳过（{pytest_result.get('reason')}）")

        self.ui.output_area.append("=" * 80)

    def _ask_writeback(self, work_dir: str, applied_files: List[str]):
        """询问用户是否回写原文件（默认禁用自动回写）"""
        if getattr(self, "enable_auto_writeback", False):
            self._write_back_from_workspace(work_dir, applied_files)
            self.ui.output_area.append("✅ 已自动回写到原始文件")
            return

        reply = QMessageBox.question(
            self.ui,
            "补丁应用成功",
            f"已成功处理文件：\n{chr(10).join(applied_files) if applied_files else '(来自统一 diff，多文件可能已变更)'}\n\n"
            f"临时文件位于:\n{work_dir}\n\n"
            f"是否将修改写回原始文件？\n\n"
            f"⚠️ 警告：这将覆盖原文件！建议先备份。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes and applied_files:
            self._write_back_from_workspace(work_dir, applied_files)
            self.ui.output_area.append("✅ 已回写到原始文件")
        else:
            self.ui.output_area.append(f"ℹ️ 已取消回写。修改后的文件保存在: {work_dir}")

    # -------------------- 自动应用与验证（核心流程） --------------------
    def try_auto_apply_and_verify(self, ai_text: str):
        """
        自动尝试应用补丁并验证（支持多种格式）
        优先级：
        1) 整段 unified diff（```diff/patch 或 裸 ---/+++ + @@ 或 diff --git）
        2) 带文件名的 python 代码块（```python 相对路径.py）
        """
        if not ai_text:
            return

        self.ui.output_area.append("\n" + "=" * 80)
        self.ui.output_area.append("🔧 尝试自动应用补丁...")
        self.ui.output_area.append("=" * 80)

        diffs = self._parse_unified_diffs(ai_text)

        if diffs:
            self.ui.output_area.append(f"✅ 找到 {len(diffs)} 个 unified diff 块")
            work_dir = self._workspace_from_uploaded()
            self.ui.output_area.append(f"🧪 已创建临时工作区: {work_dir}")

            any_ok = False
            for _, diff_content in diffs:
                if self._apply_unified_diff_patchset(work_dir, diff_content):
                    any_ok = True
            if any_ok:
                self.ui.output_area.append("✅ 已应用 unified diff 补丁。")
                after = self._verify_workspace(work_dir, timeout_sec=10)
                self._show_verification_result(after)
                before = getattr(self, "_last_local_scan_result", {})
                # 计算实际变更文件
                changed = self._diff_changed_files(work_dir)
                self._persist_metrics(before, after, {"applied_files": changed})
                self._ask_writeback(work_dir, changed)
                return
            else:
                self.ui.output_area.append("❌ 所有 diff 补丁应用均失败")

        # 代码块兜底
        self.ui.output_area.append("ℹ️ 未找到可用的 unified diff，尝试解析完整代码块...")
        code_blocks = self._parse_inline_code_blocks(ai_text)

        if code_blocks:
            self.ui.output_area.append(f"✅ 找到 {len(code_blocks)} 个代码块")
            work_dir = self._workspace_from_uploaded()
            self.ui.output_area.append(f"🧪 已创建临时工作区: {work_dir}")

            if self._apply_inline_code_blocks(work_dir, code_blocks):
                applied_files = [fname for (fname, _) in code_blocks]
                self.ui.output_area.append(f"🩹 已写入代码块到文件：{applied_files}")

                after = self._verify_workspace(work_dir, timeout_sec=10)
                self._show_verification_result(after)
                before = getattr(self, "_last_local_scan_result", {})
                # 以工作区实际差异为准
                changed = self._diff_changed_files(work_dir)
                self._persist_metrics(before, after, {"applied_files": changed})
                self._ask_writeback(work_dir, changed)
            else:
                self.ui.output_area.append("❌ 代码块写入失败")
        else:
            self.ui.output_area.append("❌ 无法应用补丁（既没有 diff 也没有代码块）")
            self.ui.output_area.append("💡 建议：请在提示词中明确要求 AI 输出标准 unified diff 或带文件名的完整代码块")

    # -------------------- 配置管理（原样保留） --------------------
    def load_configs(self, preserve_selection=None):
        settings = QSettings("config/config_ai.ini", QSettings.IniFormat)
        self.configs = {}

        sections = settings.childGroups()
        for section in sections:
            settings.beginGroup(section)
            self.configs[section] = {
                "api_base": settings.value("api_base", ""),
                "api_key": settings.value("api_key", ""),
                "model": settings.value("model", "")
            }
            settings.endGroup()

        if not self.configs:
            self.ui.config_combo.clear()
            self.ui.config_combo_1.clear()
            return

        current_index = self.ui.config_combo.currentIndex()
        self.ui.config_combo.clear()
        self.ui.config_combo.addItems(self.configs.keys())
        self.ui.config_combo_1.clear()
        self.ui.config_combo_1.addItems(self.configs.keys())
        if preserve_selection:
            new_index = self.ui.config_combo.findText(preserve_selection)
            self.ui.config_combo.setCurrentIndex(new_index if new_index != -1 else 0)
        elif current_index >= 0:
            self.ui.config_combo.setCurrentIndex(min(current_index, self.ui.config_combo.count() - 1))

    def update_config(self):
        title = self.ui.config_combo.currentText()
        self.ui.config_combo_1.setCurrentText(title)

    def update_config_1(self):
        title = self.ui.config_combo_1.currentText()
        self.ui.config_combo.setCurrentText(title)

    def new_prompt(self):
        title, ok = QInputDialog.getText(self.ui, "新增提示词", "请输入提示词标题:")
        if ok and title:
            content, ok = QInputDialog.getMultiLineText(self.ui, "新增提示词", "请输入提示词内容:")
            if ok and content:
                self.prompts[title] = content
                self.save_prompts_to_file()
                self.load_prompts()
                self.ui.prompt_combo.setCurrentText(title)

    def delete_prompt(self):
        current_title = self.ui.prompt_combo.currentText()
        if not current_title:
            return
        confirm = QMessageBox.question(
            self.ui,
            "确认删除",
            f"确定要删除提示词【{current_title}】吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            del self.prompts[current_title]
            self.save_prompts_to_file()
            self.load_prompts()

    def save_prompt(self):
        current_title = self.ui.prompt_combo.currentText()
        new_content = self.ui.prompt_edit.toPlainText()
        if current_title and new_content:
            self.prompts[current_title] = new_content
            self.save_prompts_to_file()
            QMessageBox.information(self.ui, "提示", "提示词保存成功！")

    def save_prompts_to_file(self):
        try:
            content = ""
            for title, prompt in self.prompts.items():
                content += f"### {title}\n```\n{prompt}\n```\n\n"
            with open("config/提示词.md", "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.critical(self.ui, "错误", f"保存提示词失败: {str(e)}")

    def save_configs(self):
        settings = QSettings("config/config_ai.ini", QSettings.IniFormat)
        settings.clear()
        for name, config in self.configs.items():
            settings.beginGroup(name)
            settings.setValue("api_base", config["api_base"])
            settings.setValue("api_key", config["api_key"])
            settings.setValue("model", config["model"])
            settings.endGroup()

    def new_config(self):
        name, ok = QInputDialog.getText(self.ui, "新建配置", "配置名称:")
        if ok and name:
            self.configs[name] = {
                "api_base": "http://localhost:11434/api/generate",
                "api_key": "",
                "model": "deepseek-r1:1.5b"
            }
            self.save_configs()
            self.load_configs()
            self.ui.config_combo.setCurrentText(name)

    def save_config(self):
        name = self.ui.config_combo.currentText()
        if name:
            current_name = self.ui.config_combo.currentText()
            self.configs[name] = {
                "api_base": self.ui.conf_api_base.text(),
                "api_key": self.ui.conf_api_key.text(),
                "model": self.ui.conf_model.text()
            }
            self.save_configs()
            self.load_configs(preserve_selection=current_name)
            QMessageBox.information(self.ui, "成功", "配置保存成功！")

    def del_config(self):
        name = self.ui.config_combo.currentText()
        if name in self.configs:
            reply = QMessageBox.question(
                self.ui,
                "确认删除",
                f"确定要删除配置 【{name}】 吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                del self.configs[name]
                self.save_configs()
                self.refresh_config()

    def refresh_config(self):
        self.ui.config_combo.setCurrentIndex(0)
        self.ui.config_combo_1.setCurrentIndex(0)
        self.ui.conf_api_base.setText('')
        self.ui.conf_api_key.setText('')
        self.ui.conf_model.setText('')
        self.load_configs()

    def load_config(self):
        name = self.ui.config_combo.currentText()
        if name in self.configs:
            config = self.configs[name]
            self.ui.conf_api_base.setText(config["api_base"])
            self.ui.conf_api_key.setText(config["api_key"])
            self.ui.conf_model.setText(config["model"])

    def run_multi_agent_workflow(self):
        """使用多Agent协作模式进行修复（简化版 - 直接扫描修复）"""
        if OrchestratorAgent is None:
            QMessageBox.critical(self.ui, "错误",
                                 "多Agent系统未安装，请检查 agents/ 目录\n\n"
                                 "需要的文件：\n"
                                 "- agents/orchestrator_agent.py\n"
                                 "- agents/scanner_agent.py\n"
                                 "- agents/analyzer_agent.py\n"
                                 "- agents/fixer_agent.py\n"
                                 "- agents/verifier_agent.py"
                                 )
            return

        try:
            self.ui.output_area.append("\n" + "=" * 80)
            self.ui.output_area.append("🚀 启动多Agent协作修复系统")
            self.ui.output_area.append("=" * 80)
            self.ui.output_area.repaint()
            QApplication.processEvents()

            # ===== 步骤1：收集上传的文件 =====
            files = self._collect_uploaded_files()
            if not files:
                QMessageBox.warning(self.ui, "警告", "未检测到上传文件！\n请先上传代码文件。")
                return

            self.ui.output_area.append(f"\n📂 收集到 {len(files)} 个文件")

            # 显示文件列表（前10个）
            for i, file_info in enumerate(files[:10], 1):
                filename = file_info.get("file", "unknown")
                self.ui.output_area.append(f"   {i}. {filename}")

            if len(files) > 10:
                self.ui.output_area.append(f"   ... 还有 {len(files) - 10} 个文件")

            # 按语言分类统计
            try:
                from utils.language_detector import Language, LanguageDetector
                classified = LanguageDetector.classify_files(files)

                self.ui.output_area.append(f"\n📊 语言分布:")
                for lang, file_list in classified.items():
                    if file_list and lang != Language.UNKNOWN:
                        lang_info = LanguageDetector.get_language_info(lang)
                        self.ui.output_area.append(f"   • {lang_info['name']}: {len(file_list)} 个文件")
            except Exception as e:
                self.ui.output_area.append(f"   ⚠️ 语言检测失败: {e}")

            self.ui.output_area.repaint()
            QApplication.processEvents()

            # ===== 步骤2：配置LLM（如果启用） =====
            llm_client = None
            api_key = self.ui.conf_api_key.text().strip()

            if api_key:
                try:
                    from openai import OpenAI
                    llm_client = OpenAI(
                        api_key=api_key,
                        base_url=self.ui.conf_api_base.text().strip() or None
                    )
                    model = self.ui.conf_model.text() or "gpt-3.5-turbo"
                    self.ui.output_area.append(f"\n✅ LLM已配置: {model}")
                except Exception as e:
                    self.ui.output_area.append(f"\n⚠️ LLM配置失败: {e}")
                    self.ui.output_area.append("   将仅使用规则修复")
            else:
                self.ui.output_area.append("\nℹ️ 未配置LLM，将仅使用规则修复")

            # ===== 步骤3：构建配置 =====
            config = {
                "scanner": {
                    "enable_external": True,  # 启用外部工具
                    "enable_dynamic": True,  # 启用编译检查
                    "timeout": 60
                },
                "analyzer": {},
                "fixer": {
                    "llm_client": llm_client,
                    "use_rules": True,
                    "use_llm": llm_client is not None
                },
                "verifier": {
                    "timeout": 60
                }
            }

            self.ui.output_area.append("\n" + "=" * 80)
            self.ui.output_area.append("⚙️ 系统配置")
            self.ui.output_area.append("=" * 80)
            self.ui.output_area.append(
                f"   • 外部工具扫描: {'✅ 启用' if config['scanner']['enable_external'] else '❌ 禁用'}")
            self.ui.output_area.append(
                f"   • 编译检查: {'✅ 启用' if config['scanner']['enable_dynamic'] else '❌ 禁用'}")
            self.ui.output_area.append(f"   • 规则修复: {'✅ 启用' if config['fixer']['use_rules'] else '❌ 禁用'}")
            self.ui.output_area.append(f"   • LLM修复: {'✅ 启用' if config['fixer']['use_llm'] else '❌ 禁用'}")
            self.ui.output_area.append("=" * 80)
            self.ui.output_area.repaint()
            QApplication.processEvents()

            # ===== 步骤4：创建协调Agent并执行 =====
            self.ui.output_area.append("\n🤖 初始化多Agent系统...")
            orchestrator = OrchestratorAgent(config)

            input_data = {
                "files": files,
                "user_request": "",  # 不需要用户需求
                "test_cases": []
            }

            # 执行多Agent工作流
            self.ui.output_area.append("\n" + "=" * 80)
            self.ui.output_area.append("▶️ 开始执行: 扫描 → 分析 → 修复 → 验证")
            self.ui.output_area.append("=" * 80)
            self.ui.output_area.repaint()
            QApplication.processEvents()

            # 阶段1: 感知
            self.ui.output_area.append("\n📡 阶段 1/4: 感知输入...")
            self.ui.output_area.repaint()
            QApplication.processEvents()
            perception = orchestrator.perceive(input_data)

            # 阶段2: 决策
            self.ui.output_area.append("🧠 阶段 2/4: 制定策略...")
            self.ui.output_area.repaint()
            QApplication.processEvents()
            decision = orchestrator.decide(perception)
            decision.update(perception)

            # 阶段3: 执行
            self.ui.output_area.append("⚙️ 阶段 3/4: 执行修复...")
            self.ui.output_area.append("   (这可能需要几分钟，请耐心等待...)")
            self.ui.output_area.repaint()
            QApplication.processEvents()

            results = orchestrator.execute(decision)

            # ===== 步骤5：显示结果 =====
            self.ui.output_area.append("\n" + "=" * 80)
            self.ui.output_area.append("📊 执行完成 - 结果总览")
            self.ui.output_area.append("=" * 80)

            if not results.get("success"):
                error_msg = results.get("error", "未知错误")
                self.ui.output_area.append(f"\n❌ 执行失败: {error_msg}")
                QMessageBox.critical(self.ui, "执行失败", f"多Agent系统执行失败:\n{error_msg}")
                return

            # 扫描结果
            scan_results = results.get("scan_results", {})
            scan_summary = scan_results.get("summary", {})

            self.ui.output_area.append("\n🔍 扫描结果:")
            total_defects = scan_summary.get('total_defects', 0)
            self.ui.output_area.append(f"   • 发现问题: {total_defects} 个")

            if total_defects > 0:
                by_severity = scan_summary.get("by_severity", {})
                self.ui.output_area.append(f"   • 高危: {by_severity.get('HIGH', 0)} 个")
                self.ui.output_area.append(f"   • 中危: {by_severity.get('MEDIUM', 0)} 个")
                self.ui.output_area.append(f"   • 低危: {by_severity.get('LOW', 0)} 个")

                # 按语言显示
                by_language = scan_results.get("by_language", {})
                if by_language:
                    self.ui.output_area.append(f"\n   按语言分布:")
                    for lang_name, lang_data in by_language.items():
                        total = lang_data.get("summary", {}).get("total", 0)
                        if total > 0:
                            self.ui.output_area.append(f"     - {lang_name.upper()}: {total} 个问题")
            else:
                self.ui.output_area.append("   ✅ 未发现明显问题！代码质量良好。")

            # 修复结果
            fix_results = results.get("fix_results", {})
            fix_summary = fix_results.get("summary", {})

            self.ui.output_area.append("\n🔧 修复结果:")
            self.ui.output_area.append(f"   • 处理文件: {fix_summary.get('total_files', 0)} 个")
            self.ui.output_area.append(f"   • 成功修复: {fix_summary.get('successfully_fixed', 0)} 个")
            self.ui.output_area.append(f"   • 修复失败: {fix_summary.get('failed', 0)} 个")
            self.ui.output_area.append(f"   • 总修复数: {fix_summary.get('total_fixes', 0)} 处")

            # 验证结果
            verification = results.get("verification", {})
            verify_summary = verification.get("summary", {})

            self.ui.output_area.append("\n✅ 验证结果:")
            self.ui.output_area.append(f"   • 验证文件: {verify_summary.get('total_files', 0)} 个")
            self.ui.output_area.append(f"   • 编译成功: {verify_summary.get('compile_success', 0)} 个")
            self.ui.output_area.append(f"   • 编译失败: {verify_summary.get('compile_failed', 0)} 个")

            avg_fix_rate = verify_summary.get('avg_fix_rate', 0)
            if avg_fix_rate > 0:
                self.ui.output_area.append(f"   • 平均修复率: {avg_fix_rate:.1f}%")

            # 耗时统计
            exec_time = results.get("execution_time", {})
            if exec_time:
                total_time = sum(exec_time.values())
                self.ui.output_area.append(f"\n⏱️ 总耗时: {total_time:.2f} 秒")

            self.ui.output_area.append("\n" + "=" * 80)
            self.ui.output_area.append("✨ 多Agent协作修复完成！")
            self.ui.output_area.append("=" * 80)

            # ===== 步骤6：保存修复后的文件（如果有） =====
            fixed_files = fix_results.get("fixed_files", [])

            if fixed_files:
                self.ui.output_area.append(f"\n💾 成功修复了 {len(fixed_files)} 个文件")

                reply = QMessageBox.question(
                    self.ui,
                    "保存修复后的代码",
                    f"是否保存修复后的代码？\n\n"
                    f"共 {len(fixed_files)} 个文件\n\n"
                    f"选择 Yes：选择目录保存\n"
                    f"选择 No：仅查看结果\n\n"
                    f"⚠️ 注意：将保存到新目录，不会覆盖原文件",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    save_dir = QFileDialog.getExistingDirectory(
                        self.ui,
                        "选择保存目录",
                        "",
                        QFileDialog.ShowDirsOnly
                    )

                    if save_dir:
                        try:
                            import os
                            saved_count = 0

                            for fixed_file in fixed_files:
                                filename = fixed_file.get("file", "unknown")
                                content = fixed_file.get("content", "")

                                # 保存为 fixed_原文件名
                                save_path = os.path.join(save_dir, f"fixed_{filename}")

                                with open(save_path, 'w', encoding='utf-8') as f:
                                    f.write(content)

                                saved_count += 1

                            self.ui.output_area.append(f"\n✅ 已保存 {saved_count} 个文件到:")
                            self.ui.output_area.append(f"   {save_dir}")

                            QMessageBox.information(
                                self.ui,
                                "保存成功",
                                f"已成功保存 {saved_count} 个文件到:\n{save_dir}"
                            )

                        except Exception as e:
                            self.ui.output_area.append(f"\n❌ 保存失败: {e}")
                            QMessageBox.critical(self.ui, "错误", f"保存文件失败:\n{str(e)}")
            else:
                self.ui.output_area.append("\nℹ️ 没有需要保存的修复文件")

            # ===== 步骤7：询问是否查看详细结果 =====
            if total_defects > 0:
                show_details = QMessageBox.question(
                    self.ui,
                    "查看详细结果",
                    "是否查看详细的问题列表？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )

                if show_details == QMessageBox.Yes:
                    self._show_detailed_results(results)

            # 滚动到底部
            self.ui.output_area.moveCursor(QTextCursor.End)

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()

            self.ui.output_area.append(f"\n" + "=" * 80)
            self.ui.output_area.append(f"❌ 系统异常")
            self.ui.output_area.append("=" * 80)
            self.ui.output_area.append(f"{str(e)}")
            self.ui.output_area.append(f"\n详细错误:")
            self.ui.output_area.append(f"{error_trace}")

            QMessageBox.critical(
                self.ui,
                "系统错误",
                f"多Agent系统执行异常:\n\n{str(e)}\n\n详细信息已显示在输出区域"
            )

    def _show_detailed_results(self, results: Dict[str, Any]):
        """显示详细的扫描和修复结果（辅助方法）"""
        self.ui.output_area.append("\n" + "=" * 80)
        self.ui.output_area.append("📋 详细结果")
        self.ui.output_area.append("=" * 80)

        # 显示扫描的详细问题（最多30个）
        scan_results = results.get("scan_results", {})
        by_language = scan_results.get("by_language", {})

        for lang_name, lang_data in by_language.items():
            builtin_issues = lang_data.get("builtin", [])

            if builtin_issues:
                self.ui.output_area.append(f"\n📌 {lang_name.upper()} - 发现的问题 (前30个):")

                for i, issue in enumerate(builtin_issues[:30], 1):
                    severity = issue.get("severity", "UNKNOWN")
                    severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")

                    self.ui.output_area.append(
                        f"   {i}. {severity_icon} {issue.get('file', 'unknown')}:"
                        f"{issue.get('line', '?')} - [{issue.get('rule_id', '')}] "
                        f"{issue.get('message', '')}"
                    )

                if len(builtin_issues) > 30:
                    self.ui.output_area.append(f"   ... 还有 {len(builtin_issues) - 30} 个问题")

        # 显示修复详情
        fix_results = results.get("fix_results", {})
        fix_by_language = fix_results.get("by_language", {})

        for lang_name, lang_data in fix_by_language.items():
            files = lang_data.get("files", [])

            if files:
                self.ui.output_area.append(f"\n🔧 {lang_name.upper()} - 修复详情:")

                for file_result in files:
                    filename = file_result.get("file", "unknown")
                    success = file_result.get("success", False)

                    if success:
                        self.ui.output_area.append(
                            f"   ✅ {filename} - "
                            f"方法: {file_result.get('method', '?')}, "
                            f"修复数: {file_result.get('fixed_count', 0)}"
                        )
                    else:
                        self.ui.output_area.append(
                            f"   ❌ {filename} - "
                            f"错误: {file_result.get('error_message', '未知错误')}"
                        )

        self.ui.output_area.append("\n" + "=" * 80)