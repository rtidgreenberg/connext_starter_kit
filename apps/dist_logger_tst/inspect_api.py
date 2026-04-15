import rti.connextdds as dds
import sys

dr = dds.DynamicData.DataReader
sel = dr.Selector

print("=== Selector public methods ===")
for m in sorted(dir(sel)):
    if not m.startswith('_'):
        obj = getattr(sel, m, None)
        doc = ""
        if obj and hasattr(obj, '__doc__') and obj.__doc__:
            doc = obj.__doc__.strip().split('\n')[0]
        print(f"  {m}: {doc[:120]}")

print("\n=== DataReader read/take method signatures ===")
for name in ['read', 'take', 'read_data', 'take_data', 'read_loaned', 'take_loaned', 'select']:
    method = getattr(dr, name, None)
    if method and method.__doc__:
        lines = [l.strip() for l in method.__doc__.split('\n') if l.strip()][:5]
        print(f"\n  {name}():")
        for l in lines:
            print(f"    {l[:120]}")
    else:
        print(f"\n  {name}(): no docstring")

# Check async methods
print("\n=== Async reader methods ===")
try:
    import rti.asyncio
    for m in sorted(dir(rti.asyncio)):
        if not m.startswith('_'):
            print(f"  rti.asyncio.{m}")
except Exception as e:
    print(f"  Error: {e}")

# Check if there's take_next or read_next
print("\n=== Looking for next_sample / take_next ===")
for m in sorted(dir(dr)):
    if 'next' in m.lower() or 'single' in m.lower() or 'one' in m.lower():
        print(f"  {m}")

if not any('next' in m.lower() or 'single' in m.lower() for m in dir(dr)):
    print("  (none found)")

# Check SampleInfo fields
print("\n=== SampleInfo fields ===")
si = dds.SampleInfo
for m in sorted(dir(si)):
    if not m.startswith('_'):
        print(f"  {m}")

sys.stdout.flush()
