#!/usr/bin/env python3
"""从工具目录生成索引 — 防 README/文档工具计数漂移。

用法：
    uv run python scripts/gen_tool_index.py            # 打印 Markdown 索引
    uv run python scripts/gen_tool_index.py --check docs/TOOL_INDEX.md
                                                        # 校验文档与目录一致（CI 可用）

事实源：router/tools.py::_CATEGORIES（与 GET /api/tools 同源）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_index() -> str:
    from router.tools import _CATEGORIES

    lines = [
        "# 工具索引（脚本生成，勿手改）",
        "",
        "> 生成命令：`uv run python scripts/gen_tool_index.py`；事实源 `router/tools.py::_CATEGORIES`（与 `GET /api/tools` 同源）。",
        "",
    ]
    total = 0
    for cat_id, cat_name, tools in _CATEGORIES:
        count = len(tools)
        total += count
        lines.append(f"## {cat_name}（{cat_id}）— {count} 个")
        lines.append("")
        for t in tools:
            desc = (getattr(t, "description", "") or "").strip().splitlines()
            lines.append(f"- `{t.name}` — {desc[0] if desc else ''}")
        lines.append("")
    header = [
        "# 工具索引（脚本生成，勿手改）",
        "",
        f"> 共 {len(_CATEGORIES)} 类 / {total} 个工具。生成命令：`uv run python scripts/gen_tool_index.py`；事实源 `router/tools.py::_CATEGORIES`（与 `GET /api/tools` 同源）。",
        "",
    ]
    return "\n".join(header + lines[4:])


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        target = Path(sys.argv[2])
        if not target.is_file():
            print(f"FAIL: {target} 不存在——先运行 gen_tool_index.py 生成")
            return 1
        current = build_index()
        if target.read_text(encoding="utf-8").strip() != current.strip():
            print(f"FAIL: {target} 与工具目录不一致——请重新生成（工具增删后必跑）")
            return 1
        print(f"OK: {target} 与工具目录一致")
        return 0
    print(build_index())
    return 0


if __name__ == "__main__":
    sys.exit(main())
