"""Tải bộ dữ liệu DAD từ GitHub (github.com/dad-repository/dad) vào data/raw.

Dữ liệu không được commit vào repo này vì repo gốc chưa ghi license rõ ràng.
"""
from __future__ import annotations

import io
import os
import urllib.request
import zipfile

DAD_ZIP_URL = "https://codeload.github.com/dad-repository/dad/zip/refs/heads/master"


def ensure_dad(raw_dir: str) -> list[str]:
    """Tải và giải nén nếu data/raw chưa có đủ 7 PCAP. Trả về danh sách file trong raw_dir."""
    os.makedirs(raw_dir, exist_ok=True)
    have = [f for f in os.listdir(raw_dir) if f.endswith(".pcap")]
    if len(have) < 7:
        print("Đang tải DAD từ GitHub...")
        with urllib.request.urlopen(DAD_ZIP_URL, timeout=120) as r:
            data = r.read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                base = os.path.basename(name)
                if base.endswith((".pcap", ".csv", ".xml")) or base == "README.md":
                    with z.open(name) as src, open(os.path.join(raw_dir, base), "wb") as dst:
                        dst.write(src.read())
        print("Xong.")
    return sorted(os.listdir(raw_dir))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    for f in ensure_dad(os.path.join(here, "..", "data", "raw")):
        print(f)
