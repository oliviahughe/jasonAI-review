"""
初始化 Fly.io volume 数据目录。

若 DATA_DIR 为空，则把镜像内可用的 profile/ 和 raw/ 种子数据复制过去。
chroma_db 不做跨平台复制，保留给云端重新 ingest。
"""

import os
import shutil
from pathlib import Path


def is_effectively_empty(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    return not any(path.iterdir())


def sync_seed_data(source_root: Path, data_root: Path) -> bool:
    """当 data_root 为空时，同步 profile/ 与 raw/ 作为初始化种子。"""
    data_root.mkdir(parents=True, exist_ok=True)
    if not is_effectively_empty(data_root):
        return False

    copied_any = False
    for dirname in ("profile", "raw"):
        src = source_root / dirname
        dst = data_root / dirname
        if not src.exists():
            continue
        shutil.copytree(src, dst, dirs_exist_ok=True)
        copied_any = True

    return copied_any


def main():
    app_root = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parents[1]))
    data_root = Path(os.environ.get("DATA_DIR", "/data"))
    copied = sync_seed_data(source_root=app_root, data_root=data_root)
    message = "seed data copied" if copied else "data volume already initialized"
    print(message)


if __name__ == "__main__":
    main()
