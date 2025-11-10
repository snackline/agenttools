# run_tests.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import warnings
import pytest
import sys
import os

# 过滤掉pytest的警告
warnings.filterwarnings("ignore", category=pytest.PytestAssertRewriteWarning)

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 运行测试
if __name__ == "__main__":
    pytest.main([
        "tabs/test_tab_ai_security.py",
        "-v",
        "--tb=short",
        "-W", "ignore::pytest.PytestAssertRewriteWarning"
    ])