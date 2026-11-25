"""架构约束：四层之间只能从上往下依赖。

core（纯逻辑）← infra（IO）← services（用例）← interfaces（协议）。
同层可以互相引用；任何向下越级都允许，向上（core 引 services）或跨级回绕都算违约。
"""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "mote")
LAYERS = {"core": 0, "infra": 1, "services": 2, "interfaces": 3}
NAMES = {level: name for name, level in LAYERS.items()}


def _dotted(path):
    rel = os.path.relpath(path, ROOT).replace(os.sep, ".")
    return rel[:-3] if rel.endswith(".py") else rel


def _layer_of(dotted):
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[0] == "mote" and parts[1] in LAYERS:
        return LAYERS[parts[1]], parts[1]
    return None, None


def _package_of(dotted):
    """模块所属包：文件是 __init__.py 时包就是它自己。"""
    if dotted.endswith(".__init__"):
        return dotted[: -len(".__init__")]
    return dotted.rsplit(".", 1)[0]


def _targets(module_path, node):
    """把一条 import 解析成它实际引用的绝对模块名。"""
    dotted = _dotted(module_path)
    package = _package_of(dotted)
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        parts = package.split(".")
        if node.level > 1:
            parts = parts[: -(node.level - 1)]
        if node.module:
            return [".".join(parts + [node.module])]
        return [".".join(parts + [alias.name]) for alias in node.names]
    return [node.module] if node.module else []


class LayerTest(unittest.TestCase):
    def test_imports_point_downward(self):
        problems = []
        for dirpath, dirs, files in os.walk(PACKAGE):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                own, own_name = _layer_of(_dotted(path))
                if own is None:          # 包根与 __main__.py 在四层之上
                    continue
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), path)
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Import, ast.ImportFrom)):
                        continue
                    for target in _targets(path, node):
                        level, target_name = _layer_of(target)
                        if level is None or level <= own:
                            continue
                        problems.append(
                            f"{os.path.relpath(path, ROOT)}: {own_name} 不能依赖 "
                            f"{target_name}（{target}）")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_every_layer_has_entry(self):
        for name in LAYERS:
            self.assertTrue(os.path.isfile(os.path.join(PACKAGE, name, "__init__.py")),
                            f"缺少 {name}/__init__.py")
