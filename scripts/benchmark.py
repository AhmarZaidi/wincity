"""
WinCity Performance & Resource Profiler.
Measures RAM, CPU utilization, thread count, handle count, and wakeups.

Usage:
  python scripts/benchmark.py --run python --duration 10 --save python_baseline.json
  python scripts/benchmark.py --run rust   --duration 10 --save rust_bench.json
  python scripts/benchmark.py --compare python_baseline.json rust_bench.json
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


def profile_process(proc: psutil.Process, duration: float = 15.0, sample_interval: float = 0.5) -> dict:
    """Sample resource metrics for a target process over a given duration."""
    cpu_samples = []
    rss_samples = []
    private_samples = []
    threads_samples = []
    handles_samples = []

    # Prime CPU percent baseline
    try:
        proc.cpu_percent(interval=None)
    except Exception:
        pass

    start_cpu_times = proc.cpu_times()
    start_time = time.time()
    end_time = start_time + duration

    print(f"[*] Profiling PID {proc.pid} ({proc.name()}) for {duration:.1f} seconds...")

    while time.time() < end_time and proc.is_running():
        try:
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_info()
            rss_mb = mem.rss / (1024 * 1024)
            private_mb = getattr(mem, "private", mem.rss) / (1024 * 1024)
            threads = proc.num_threads()
            handles = proc.num_handles() if hasattr(proc, "num_handles") else 0

            cpu_samples.append(cpu)
            rss_samples.append(rss_mb)
            private_samples.append(private_mb)
            threads_samples.append(threads)
            handles_samples.append(handles)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break

        time.sleep(sample_interval)

    end_cpu_times = proc.cpu_times() if proc.is_running() else start_cpu_times
    total_cpu_time_ms = ((end_cpu_times.user - start_cpu_times.user) +
                         (end_cpu_times.system - start_cpu_times.system)) * 1000.0

    avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    peak_cpu = max(cpu_samples) if cpu_samples else 0.0
    avg_rss = sum(rss_samples) / len(rss_samples) if rss_samples else 0.0
    peak_rss = max(rss_samples) if rss_samples else 0.0
    avg_private = sum(private_samples) / len(private_samples) if private_samples else 0.0
    peak_private = max(private_samples) if private_samples else 0.0
    avg_threads = sum(threads_samples) / len(threads_samples) if threads_samples else 0.0
    avg_handles = sum(handles_samples) / len(handles_samples) if handles_samples else 0.0

    return {
        "duration_sec": duration,
        "samples_count": len(cpu_samples),
        "cpu_avg_pct": round(avg_cpu, 2),
        "cpu_peak_pct": round(peak_cpu, 2),
        "cpu_time_total_ms": round(total_cpu_time_ms, 2),
        "ram_working_set_avg_mb": round(avg_rss, 2),
        "ram_working_set_peak_mb": round(peak_rss, 2),
        "ram_private_avg_mb": round(avg_private, 2),
        "ram_private_peak_mb": round(peak_private, 2),
        "threads_avg": round(avg_threads, 1),
        "handles_avg": round(avg_handles, 1),
    }


def print_report(name: str, metrics: dict):
    print("\n" + "=" * 60)
    print(f"  RESOURCE PROFILE REPORT: {name}")
    print("=" * 60)
    print(f"  Observation Duration : {metrics['duration_sec']}s ({metrics['samples_count']} samples)")
    print(f"  Average CPU Usage    : {metrics['cpu_avg_pct']}%")
    print(f"  Peak CPU Usage       : {metrics['cpu_peak_pct']}%")
    print(f"  Total CPU Time Used  : {metrics['cpu_time_total_ms']} ms")
    print(f"  Average RAM (RSS)    : {metrics['ram_working_set_avg_mb']} MB")
    print(f"  Peak RAM (RSS)       : {metrics['ram_working_set_peak_mb']} MB")
    print(f"  Private Memory       : {metrics['ram_private_avg_mb']} MB")
    print(f"  Active Threads       : {metrics['threads_avg']}")
    print(f"  Active OS Handles    : {metrics['handles_avg']}")
    print("=" * 60 + "\n")


def compare_reports(file1: Path, file2: Path):
    d1 = json.loads(file1.read_text(encoding="utf-8"))
    d2 = json.loads(file2.read_text(encoding="utf-8"))

    print("\n" + "=" * 75)
    print(f"  COMPARISON: Before ({file1.stem}) vs After ({file2.stem})")
    print("=" * 75)
    print(f"{'Metric':<28} | {'Before':<14} | {'After':<14} | {'Delta / Improvement':<16}")
    print("-" * 75)

    comparisons = [
        ("Average RAM (Working Set)", "ram_working_set_avg_mb", "MB", True),
        ("Peak RAM (Working Set)",    "ram_working_set_peak_mb", "MB", True),
        ("Private Memory",           "ram_private_avg_mb", "MB", True),
        ("Average CPU %",            "cpu_avg_pct", "%", True),
        ("Peak CPU %",               "cpu_peak_pct", "%", True),
        ("Total CPU Time (ms)",       "cpu_time_total_ms", "ms", True),
        ("Active OS Threads",        "threads_avg", "", True),
        ("Active OS Handles",        "handles_avg", "", True),
    ]

    for label, key, unit, lower_is_better in comparisons:
        v1 = d1.get(key, 0)
        v2 = d2.get(key, 0)
        diff = v2 - v1
        pct = (diff / v1 * 100) if v1 != 0 else 0

        u_str = f" {unit}" if unit else ""
        v1_str = f"{v1}{u_str}"
        v2_str = f"{v2}{u_str}"

        if diff < 0:
            change_str = f"-{abs(diff):.1f}{u_str} ({abs(pct):.1f}% better)"
        elif diff > 0:
            change_str = f"+{diff:.1f}{u_str} ({pct:.1f}% worse)"
        else:
            change_str = "0 (no change)"

        print(f"{label:<28} | {v1_str:<14} | {v2_str:<14} | {change_str:<16}")
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Profile WinCity resource usage.")
    parser.add_argument("--run", choices=["python", "rust"], help="Launch and profile WinCity version")
    parser.add_argument("--pid", type=int, help="Attach to existing PID")
    parser.add_argument("--duration", type=float, default=10.0, help="Benchmark duration in seconds")
    parser.add_argument("--save", type=str, help="Save JSON report to file")
    parser.add_argument("--compare", nargs=2, help="Compare two benchmark JSON files")

    args = parser.parse_args()

    if args.compare:
        compare_reports(Path(args.compare[0]), Path(args.compare[1]))
        return

    root_dir = Path(__file__).parent.parent.resolve()
    target_proc = None
    spawned_p = None

    if args.run == "python":
        main_py = root_dir / "python" / "main.py"
        py_exe = sys.executable
        spawned_p = subprocess.Popen([py_exe, str(main_py)], cwd=str(root_dir))
        time.sleep(1.0)
        target_proc = psutil.Process(spawned_p.pid)
    elif args.run == "rust":
        rust_exe = root_dir / "rust" / "target" / "release" / "wincity.exe"
        if not rust_exe.exists():
            print(f"[!] Rust executable not found at: {rust_exe}")
            print("[*] Building release binary first...")
            subprocess.run(["cargo", "build", "--release"], cwd=str(root_dir / "rust"), check=True)
        spawned_p = subprocess.Popen([str(rust_exe)], cwd=str(root_dir))
        time.sleep(1.0)
        target_proc = psutil.Process(spawned_p.pid)
    elif args.pid:
        target_proc = psutil.Process(args.pid)
    else:
        # Auto-find running process
        for p in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                name = p.info.get("name", "")
                if "main.py" in cmd or "wincity.exe" in name.lower() or "wincity" in name.lower():
                    target_proc = p
                    break
            except Exception:
                pass

        if not target_proc:
            print("[!] No running WinCity process found. Use --run python or --run rust.")
            return

    try:
        metrics = profile_process(target_proc, duration=args.duration)
        print_report(f"PID {target_proc.pid} ({target_proc.name()})", metrics)
        if args.save:
            Path(args.save).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            print(f"[OK] Saved benchmark data to: {args.save}")
    finally:
        if spawned_p:
            try:
                spawned_p.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
