"""AV 도메인 segments.json 의 file_path 형식 분석."""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

for dom, fn in (("Rec", "music"), ("Movie", "movie")):
    p = f"Data/embedded_DB/{dom}/segments.json"
    segs = json.load(open(p, "r", encoding="utf-8"))
    paths = set(s.get("file", "") for s in segs)
    abs_paths = [x for x in paths if x[1:3] == ":\\" or x[1:3] == ":/" or x.startswith("/")]
    rel_paths = [x for x in paths if x not in abs_paths]
    print(f"=== {dom} ({fn}) — segments={len(segs)}, unique paths={len(paths)} ===")
    print(f"  abs-form: {len(abs_paths)}, rel-form: {len(rel_paths)}")
    print(f"  abs sample: {abs_paths[:1]}")
    print(f"  rel sample: {rel_paths[:1]}")

    # 같은 basename 중복?
    bn_count = {}
    for x in paths:
        bn = os.path.basename(x.replace("\\", "/"))
        bn_count[bn] = bn_count.get(bn, 0) + 1
    dup_bn = {k: v for k, v in bn_count.items() if v > 1}
    print(f"  basename 중복 그룹: {len(dup_bn)}")
    if dup_bn:
        print(f"  예: {list(dup_bn.items())[:2]}")
