import json
import argparse
from collections import defaultdict
import os

def format_time(microseconds):
    """Convert microseconds to a readable string."""
    if microseconds > 1_000_000:
        return f"{microseconds / 1_000_000:.2f} s"
    return f"{microseconds / 1000:.2f} ms"

def analyze_trace(file_path, top_n=15):
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return

    print(f"Loading trace data from {file_path}...")
    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Error: Invalid JSON file.")
            return

    events = data.get('traceEvents', data) if isinstance(data, dict) else data

    op_durations = defaultdict(float)
    op_counts = defaultdict(int)
    
    transfer_stats = {
        'HtoD': {'time': 0.0, 'count': 0}, 
        'DtoH': {'time': 0.0, 'count': 0}, 
        'DtoD': {'time': 0.0, 'count': 0}  
    }

    min_ts = float('inf')
    max_ts = 0

    print("Parsing events and isolating PyTorch operators...")
    for event in events:
        if 'ts' in event and 'dur' in event:
            ts = event['ts']
            dur = event['dur']
            name = event['name']

            min_ts = min(min_ts, ts)
            max_ts = max(max_ts, ts + dur)

            # Categorize Memory Transfers
            if 'Memcpy HtoD' in name or 'Host -> Device' in name:
                transfer_stats['HtoD']['time'] += dur
                transfer_stats['HtoD']['count'] += 1
            elif 'Memcpy DtoH' in name or 'Device -> Host' in name:
                transfer_stats['DtoH']['time'] += dur
                transfer_stats['DtoH']['count'] += 1
            elif 'Memcpy DtoD' in name or 'Device -> Device' in name:
                transfer_stats['DtoD']['time'] += dur
                transfer_stats['DtoD']['count'] += 1
            else:
                # --- V3 AGGRESSIVE FILTER ---
                # Remove all Python files, locks, builtins, and background workers
                if ('.py' in name or 
                    '<built-in' in name or 
                    '_thread' in name or 
                    'lock' in name or 
                    name.startswith('PyTorch Profiler') or
                    'writer' in name.lower()):
                    continue
                
                op_durations[name] += dur
                op_counts[name] += 1

    total_trace_time = max_ts - min_ts
    if total_trace_time <= 0:
        print("Could not determine total trace time. Is the trace empty?")
        return

    # --- Print the Clean Report ---
    print("\n" + "="*50)
    print(" PyTorch Trace Profiler Summary (PURE MATH OPS) ")
    print("="*50)
    print(f"Total Trace Duration: {format_time(total_trace_time)}")
    
    print("\n--- Memory Transfer (Data Bottlenecks) ---")
    for direction, stats in transfer_stats.items():
        if stats['count'] > 0:
            pct = (stats['time'] / total_trace_time) * 100
            print(f"{direction} (e.g., {'CPU->GPU' if direction == 'HtoD' else 'GPU->CPU' if direction == 'DtoH' else 'GPU->GPU'}):")
            print(f"  Total Time: {format_time(stats['time'])} ({pct:.2f}% of total trace)")
            print(f"  Call Count: {stats['count']}")
            print(f"  Avg per call: {format_time(stats['time']/stats['count'])}")
        else:
            print(f"{direction}: No events recorded.")

    print(f"\n--- Top {top_n} PyTorch Operators & Kernels ---")
    sorted_ops = sorted(op_durations.items(), key=lambda item: item[1], reverse=True)
    
    print(f"{'Operation Name':<50} | {'Total Time':<10} | {'% Total':<7} | {'Calls':<6} | {'Avg Time'}")
    print("-" * 100)
    
    for i, (name, total_dur) in enumerate(sorted_ops[:top_n]):
        pct = (total_dur / total_trace_time) * 100
        count = op_counts[name]
        avg_dur = total_dur / count
        
        display_name = name if len(name) <= 48 else name[:45] + "..."
        print(f"{display_name:<50} | {format_time(total_dur):<10} | {pct:>5.1f}% | {count:<6} | {format_time(avg_dur)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze PyTorch pt.trace.json files.")
    parser.add_argument("trace_file", help="Path to the .pt.trace.json file")
    parser.add_argument("--top", type=int, default=15, help="Number of top functions to display")
    
    args = parser.parse_args()
    analyze_trace(args.trace_file, args.top)