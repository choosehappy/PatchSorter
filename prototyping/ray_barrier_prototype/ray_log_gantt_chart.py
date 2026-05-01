import re
import glob
from collections import defaultdict
import matplotlib.pyplot as plt


# =========================
# 1. Load logs
# =========================
log_files = glob.glob("*.log")

if not log_files:
    raise ValueError("No .log files found")

print("Reading log files:", log_files)


# =========================
# 2. Regex patterns
# =========================
start_pattern = re.compile(r"\[Worker (\d+)\] Starting loop .* at (\d+\.\d+)")
sleep_start_pattern = re.compile(r"\[Worker (\d+)\] Cycle (\d+): sleeping .* at (\d+\.\d+)")
sleep_end_pattern = re.compile(r"\[Worker (\d+)\] Cycle (\d+): finished sleeping .* at (\d+\.\d+)")
barrier_wait_pattern = re.compile(r"\[Worker (\d+)\] Cycle (\d+): waiting at barrier at (\d+\.\d+)")
barrier_pass_pattern = re.compile(r"\[Worker (\d+)\] Cycle (\d+): passed barrier at (\d+\.\d+)")


# =========================
# 3. Robust run grouping
# =========================
def find_or_create_run(t, runs, tol=2.0):
    """
    Find an existing run whose start time is within tol seconds,
    otherwise create a new run.
    """
    for existing in runs.keys():
        if abs(existing - t) < tol:
            return existing
    return t


# runs[run_start][worker][cycle] = {events}
runs = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

for file in log_files:
    with open(file, "r") as f:
        current_run_start = None

        for line in f:
            if m := start_pattern.search(line):
                worker, t = int(m.group(1)), float(m.group(2))
                current_run_start = find_or_create_run(t, runs)
                runs[current_run_start][worker]

            elif m := sleep_start_pattern.search(line):
                worker, cycle, t = int(m.group(1)), int(m.group(2)), float(m.group(3))
                runs[current_run_start][worker][cycle]["sleep_start"] = t

            elif m := sleep_end_pattern.search(line):
                worker, cycle, t = int(m.group(1)), int(m.group(2)), float(m.group(3))
                runs[current_run_start][worker][cycle]["sleep_end"] = t

            elif m := barrier_wait_pattern.search(line):
                worker, cycle, t = int(m.group(1)), int(m.group(2)), float(m.group(3))
                runs[current_run_start][worker][cycle]["barrier_wait"] = t

            elif m := barrier_pass_pattern.search(line):
                worker, cycle, t = int(m.group(1)), int(m.group(2)), float(m.group(3))
                runs[current_run_start][worker][cycle]["barrier_pass"] = t


# =========================
# 4. Build intervals
# =========================
def build_intervals(run_data):
    intervals = defaultdict(list)

    for worker, cycles in run_data.items():
        for cycle, ev in cycles.items():
            if "sleep_start" in ev and "sleep_end" in ev:
                intervals[worker].append((
                    ev["sleep_start"],
                    ev["sleep_end"] - ev["sleep_start"],
                    f"sleep_c{cycle}"
                ))

            if "barrier_wait" in ev and "barrier_pass" in ev:
                wait_duration = ev["barrier_pass"] - ev["barrier_wait"]
                if wait_duration > 0:
                    intervals[worker].append((
                        ev["barrier_wait"],
                        wait_duration,
                        f"barrier_c{cycle}"
                    ))

    return intervals


# =========================
# 5. Normalize time
# =========================
def normalize_intervals(intervals):
    all_starts = [start for segs in intervals.values() for start, _, _ in segs]
    t0 = min(all_starts)

    norm = defaultdict(list)
    for worker, segs in intervals.items():
        for start, duration, label in segs:
            norm[worker].append((start - t0, duration, label))

    return norm


# =========================
# 6. Plot Gantt
# =========================
def plot_gantt(intervals, title="Gantt Chart"):
    fig, ax = plt.subplots(figsize=(12, 4))

    workers = sorted(intervals.keys())
    y_map = {w: i for i, w in enumerate(workers)}

    for worker, segs in intervals.items():
        y = y_map[worker]

        for start, duration, label in segs:
            ax.barh(y, duration, left=start)
            ax.text(start + duration / 2, y, label,
                    ha='center', va='center', fontsize=8)

    ax.set_yticks(list(y_map.values()))
    ax.set_yticklabels([f"Worker {w}" for w in workers])
    ax.set_xlabel("Time (seconds from run start)")
    ax.set_title(title)
    ax.grid(True)

    plt.tight_layout()
    plt.show()


# =========================
# 7. Run it
# =========================
run_starts = sorted(runs.keys())

print("\nAvailable runs:")
for i, r in enumerate(run_starts):
    print(f"{i}: {r}")

selected_index = 0  # change if needed
selected_run = run_starts[selected_index]

intervals = build_intervals(runs[selected_run])
intervals = normalize_intervals(intervals)

plot_gantt(intervals, title=f"Run starting at ~{selected_run:.2f}")