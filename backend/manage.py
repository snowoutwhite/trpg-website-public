#!/usr/bin/env python
"""Django 管理命令入口。默认使用开发配置，可用 DJANGO_SETTINGS_MODULE 覆盖。"""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - 环境异常时的兜底提示
        raise ImportError(
            "无法导入 Django。请确认已执行 `uv sync` 并在 `uv run` 下运行本脚本。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
