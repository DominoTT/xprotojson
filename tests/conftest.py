import os
import sys
from pathlib import Path


# 确保项目根目录在 sys.path 首位，便于 'app' 包导入
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


