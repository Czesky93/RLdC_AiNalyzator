import time
import os

log_file = "logs/dev/backend.log"
output_file = "logs/dev/test_30min_summary.txt"
test_duration = 1800

stats = {
    "LIVE_PIPELINE_BUY": 0,
    "BUY_FILLED": 0,
    "SELL_FILLED": 0,
    "WHY_NOT_BUY_TOTAL": 0,
    "REASONS": {}
}

start_time = time.time()

with open(log_file, "r") as f:
    f.seek(0, os.SEEK_END)
    while time.time() - start_time < test_duration:
        line = f.readline()
        if not line:
            time.sleep(0.1)
            continue
        
        if "LIVE PIPELINE WHY_NOT_BUY" in line:
            stats["WHY_NOT_BUY_TOTAL"] += 1
            if "reason=" in line:
                reason = line.split("reason=")[1].split()[0]
                stats["REASONS"][reason] = stats["REASONS"].get(reason, 0) + 1
        elif "LIVE PIPELINE BUY:" in line:
            stats["LIVE_PIPELINE_BUY"] += 1
        elif "LIVE ORDER FILLED: BUY" in line:
            stats["BUY_FILLED"] += 1
        elif "LIVE ORDER FILLED: SELL" in line:
            stats["SELL_FILLED"] += 1

with open(output_file, "w") as out:
    out.write("TEST_WINDOW_MIN=30\n")
    out.write(f"LIVE_PIPELINE_BUY={stats['LIVE_PIPELINE_BUY']}\n")
    out.write(f"BUY_FILLED={stats['BUY_FILLED']}\n")
    out.write(f"SELL_FILLED={stats['SELL_FILLED']}\n")
    out.write(f"WHY_NOT_BUY_TOTAL={stats['WHY_NOT_BUY_TOTAL']}\n")
    out.write("WHY_NOT_BUY_BY_REASON:\n")
    for r, count in stats["REASONS"].items():
        out.write(f"{r}={count}\n")
