"""Auto-merge duplicate keys in query_expand.py _KO_EN dict."""
import ast, re, sys

fpath = 'App/backend/services/query_expand.py'
with open(fpath, encoding='utf-8') as f:
    src = f.read()
lines = src.splitlines(keepends=True)

tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        occurrences = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(v, ast.List):
                vals = [x.value for x in v.elts if isinstance(x, ast.Constant)]
                occurrences.setdefault(k.value, []).append((k.lineno, v.end_lineno, vals))

        dups = {k: v for k, v in occurrences.items() if len(v) > 1}
        if not dups:
            print('No duplicates found.')
            sys.exit(0)

        lines_to_delete = set()
        updates = {}  # lineno (1-based) -> merged values list

        for key, occ_list in dups.items():
            merged = list(dict.fromkeys(v for _, _, vals in occ_list for v in vals))
            first_lineno = occ_list[0][0]
            updates[first_lineno] = merged
            for lineno, end_lineno, _ in occ_list[1:]:
                for ln in range(lineno, end_lineno + 1):
                    lines_to_delete.add(ln)

        new_lines = []
        for i, line in enumerate(lines, start=1):
            if i in lines_to_delete:
                continue
            if i in updates:
                vals_str = ', '.join(repr(v) for v in updates[i])
                # Replace [...] list portion on this line
                new_line = re.sub(r'\[.*\]', '[' + vals_str + ']', line, count=1)
                new_lines.append(new_line)
            else:
                new_lines.append(line)

        with open(fpath, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        print(f'Fixed {len(dups)} duplicates: {sorted(dups.keys())}')
        print(f'Lines removed: {len(lines_to_delete)}')
        break
