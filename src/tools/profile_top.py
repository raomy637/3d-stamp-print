import pstats, sys
p = sys.argv[1]
s = pstats.Stats(p)
s.strip_dirs()
s.sort_stats("tottime")
stats = s.stats
rows = []
for (fn, line, name), (cc, nc, tt, ct, callers) in stats.items():
    if "importlib" in fn or name in ("__import__",) or "cProfile" in fn:
        continue
    rows.append((tt, ct, name, fn, line))
rows.sort(reverse=True)
tot = sum(r[0] for r in rows)
print(f"total(tottime, 已排除 import): {tot:.2f}s")
for tt, ct, name, fn, line in rows[:24]:
    print(f"{tt:7.3f}s  cum {ct:7.3f}s  {name:<38} {fn}:{line}")
