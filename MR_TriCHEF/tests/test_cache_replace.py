"""[P2B.4] replace_by_file 회귀 테스트.

목표: 동일 파일을 두 번 인덱싱해도 ids/npy/segments 가 중복 누적되지 않음을 검증.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

# stdout utf-8 (Windows)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from MR_TriCHEF.pipeline import cache  # noqa: E402


def _make_rows(n: int, dim: int, val: float) -> np.ndarray:
    return (np.ones((n, dim), dtype=np.float32) * val)


def run() -> None:
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        # ── round 1: fileA 3 rows, fileB 2 rows ─────────────────────
        cache.replace_by_file(
            cache_dir=d,
            file_keys=["a.mp4"],
            arrays={
                "Re": _make_rows(3, 8, 1.0),
                "Im": _make_rows(3, 4, 1.0),
            },
            new_ids=["a.mp4"] * 3,
            new_segs=[{"file_path": "a.mp4", "i": i} for i in range(3)],
            npy_prefix="cache_x",
            ids_file="x_ids.json",
            segs_file="segments.json",
        )
        cache.replace_by_file(
            cache_dir=d,
            file_keys=["b.mp4"],
            arrays={
                "Re": _make_rows(2, 8, 2.0),
                "Im": _make_rows(2, 4, 2.0),
            },
            new_ids=["b.mp4"] * 2,
            new_segs=[{"file_path": "b.mp4", "i": i} for i in range(2)],
            npy_prefix="cache_x",
            ids_file="x_ids.json",
            segs_file="segments.json",
        )

        Re = np.load(d / "cache_x_Re.npy")
        ids = json.loads((d / "x_ids.json").read_text(encoding="utf-8"))["ids"]
        segs = json.loads((d / "segments.json").read_text(encoding="utf-8"))
        assert Re.shape == (5, 8), f"Re shape expected (5,8) got {Re.shape}"
        assert len(ids) == 5, f"ids {len(ids)}"
        assert len(segs) == 5, f"segs {len(segs)}"
        print(f"[round1] OK — rows=5 ids=5 segs=5")

        # ── round 2: fileA re-index with 4 rows (value 9.0) ─────────
        res = cache.replace_by_file(
            cache_dir=d,
            file_keys=["a.mp4"],
            arrays={
                "Re": _make_rows(4, 8, 9.0),
                "Im": _make_rows(4, 4, 9.0),
            },
            new_ids=["a.mp4"] * 4,
            new_segs=[{"file_path": "a.mp4", "i": i} for i in range(4)],
            npy_prefix="cache_x",
            ids_file="x_ids.json",
            segs_file="segments.json",
        )
        Re = np.load(d / "cache_x_Re.npy")
        Im = np.load(d / "cache_x_Im.npy")
        ids = json.loads((d / "x_ids.json").read_text(encoding="utf-8"))["ids"]
        segs = json.loads((d / "segments.json").read_text(encoding="utf-8"))

        # b(2) + new_a(4) = 6 rows
        assert Re.shape == (6, 8), f"Re shape expected (6,8) got {Re.shape}"
        assert Im.shape == (6, 4), f"Im shape expected (6,4) got {Im.shape}"
        assert len(ids) == 6
        assert ids.count("a.mp4") == 4, f"a.mp4 count expected 4 got {ids.count('a.mp4')}"
        assert ids.count("b.mp4") == 2
        assert len(segs) == 6
        assert sum(1 for s in segs if s["file_path"] == "a.mp4") == 4
        assert res["removed"] == 3, f"removed expected 3 got {res['removed']}"
        # stale 값 1.0 행 없음 (a 는 전부 9.0)
        a_rows = Re[[i for i, x in enumerate(ids) if x == "a.mp4"]]
        assert (a_rows == 9.0).all(), "stale a.mp4 rows leaked"
        print(f"[round2] OK — rows=6 removed={res['removed']} no-stale-leak")

        # ── round 3: 존재하지 않는 파일 key → removed=0, 단순 append ─
        res = cache.replace_by_file(
            cache_dir=d,
            file_keys=["c.mp4"],
            arrays={
                "Re": _make_rows(1, 8, 3.0),
                "Im": _make_rows(1, 4, 3.0),
            },
            new_ids=["c.mp4"],
            new_segs=[{"file_path": "c.mp4", "i": 0}],
            npy_prefix="cache_x",
            ids_file="x_ids.json",
            segs_file="segments.json",
        )
        Re = np.load(d / "cache_x_Re.npy")
        assert Re.shape == (7, 8)
        assert res["removed"] == 0
        print(f"[round3] OK — rows=7 removed=0 (new file)")

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run()
