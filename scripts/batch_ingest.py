"""批量入库脚本，带限速重试"""
import time
from pathlib import Path
from ingest import ingest_article, load_settings

settings = load_settings()
data_dir = Path("/data")
raw_dir = data_dir / settings["paths"]["raw_dir"]
files = sorted(raw_dir.glob("*.md"))
ok = skip = err = 0

for i, f in enumerate(files):
    for attempt in range(5):
        try:
            r = ingest_article(str(f), settings)
            if r["status"] == "ok":
                ok += 1
                print(f"[{i+1}/{len(files)}] OK: {f.name}")
            elif r["status"] == "skipped":
                skip += 1
                print(f"[{i+1}/{len(files)}] SKIP: {f.name}")
            else:
                err += 1
                print(f"[{i+1}/{len(files)}] ERR: {r['message']}")
            break
        except Exception as e:
            if "429" in str(e) and attempt < 4:
                print(f"[{i+1}/{len(files)}] Rate limited, waiting 25s...")
                time.sleep(25)
            else:
                err += 1
                print(f"[{i+1}/{len(files)}] FAIL: {e}")
                break
    time.sleep(1)

print(f"\nDone: {ok} ingested, {skip} skipped, {err} errors")
