import os

def print_tree(start_path, max_level=10):
    """
    打印项目目录结构，不读取文件内容。
    start_path: 项目路径
    max_level: 最大递归深度（避免巨型项目）
    """

    def helper(path, prefix="", level=0):
        if level > max_level:
            print(prefix + "└── ... (max depth reached)")
            return

        try:
            items = sorted(os.listdir(path))
        except PermissionError:
            print(prefix + "└── <Permission Denied>")
            return

        for i, name in enumerate(items):
            full = os.path.join(path, name)
            is_last = (i == len(items) - 1)

            connector = "└── " if is_last else "├── "
            branch = prefix + connector + name

            print(branch)

            if os.path.isdir(full):
                new_prefix = prefix + ("    " if is_last else "│   ")
                helper(full, new_prefix, level + 1)

    print(f"\n📁 Project Tree: {start_path}\n")
    print(os.path.basename(start_path) + "/")
    helper(start_path, "")


if __name__ == "__main__":
    # ⚠️ 在这里改成你的项目根目录
    project_path = r"C:\Users\1catmint1\Desktop\link-tools-main\DebugBench-main"

    print_tree(project_path)
