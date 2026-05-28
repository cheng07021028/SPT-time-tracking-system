# -*- coding: utf-8 -*-
"""Remove old V1 paths after applying modified_files.
Run from project root:
    python tools/remove_old_v1_paths.py
This script deletes only paths listed in OLD_FILES_TO_DELETE_V1.txt and empty parent folders.
"""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
LIST_PATH = ROOT / "OLD_FILES_TO_DELETE_V1.txt"

# Fallback list for old generated Streamlit page filenames and legacy data folders.
FALLBACK = [
    "pages/01_01. #U5de5#U6642#U7d00#U9304.py",
    "pages/02_02. #U6b77#U53f2#U7d00#U9304.py",
    "pages/03_03. #U88fd#U4ee4#U7ba1#U7406.py",
    "pages/04_04. #U4eba#U54e1#U540d#U55ae.py",
    "pages/05_05. #U88fd#U4ee4#U5de5#U6642#U5206#U6790.py",
    "pages/06_06. LOG#U67e5#U8a62.py",
    "pages/07_07. #U4eca#U65e5#U672a#U7d00#U9304#U540d#U55ae.py",
    "pages/08_08. #U4eba#U54e1#U6bcf#U65e5#U5de5#U6642.py",
    "pages/09_09. #U8cc7#U6599#U6c38#U4e45#U4fdd#U5b58#U8207#U5099#U4efd.py",
    "pages/10_10. #U6b0a#U9650#U7ba1#U7406.py",
    "pages/11_11. #U767b#U5165#U7d00#U9304.py",
    "pages/12_12. #U6a21#U7d44#U6c38#U4e45#U7d00#U9304#U4e2d#U5fc3.py",
    "pages/13_13. #U7cfb#U7d71#U8a2d#U5b9a.py",
    "data/persistent_modules",
    "data/persistent_state",
    "data/database",
    "data/config",
]

def load_targets():
    if LIST_PATH.exists():
        return [line.strip() for line in LIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    return FALLBACK

def main():
    removed=[]
    for rel in load_targets():
        # never delete permanent_store
        if rel.replace("\\", "/").startswith("data/permanent_store"):
            continue
        p = ROOT / rel
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(rel + "/")
        elif p.exists():
            p.unlink()
            removed.append(rel)
    print("Removed old V1 paths:")
    for item in removed:
        print(" -", item)
    print("Done.")

if __name__ == "__main__":
    main()
