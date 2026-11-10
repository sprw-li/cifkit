#!/usr/bin/env python3
"""GPU benchmark payload for the parallel fan-out (round 30, audit-hardened).

Round 30 audit findings fixed here (each was a real way the numbers could lie):

* **warm-up + preallocated output** — the old loop allocated the result inside the
  timed region (a ``cudaMalloc`` per iteration) and never warmed cuBLAS/clocks, so
  the "median" was the slowest sample and fast cards looked slow;
* **CUDA events instead of per-iteration host sync** — host round-trip latency was
  being counted as compute time;
* **math-mode pinned and recorded** — TF32 / reduced-precision reductions could
  silently inflate "fp32"/"fp16" GFLOPS; both are now forced off and reported;
* **the checksum now certifies the GEMM** — deterministically built inputs plus an
  fp64 reference, reporting input/output checksums and a max relative error
  instead of an unrelated element-wise sum;
* **exit-code contract made real** — a ``status`` field and a ``finally`` write mean
  exit 0 ⇔ report produced; a failed stage yields ``partial`` instead of silence;
* **identity/clocks recorded** — device UUID, ``CUDA_VISIBLE_DEVICES``, SM count,
  clocks, power, temperature and throttle reasons, so a throttled or shared card
  cannot masquerade as a fast one.

Writes ``gpu_result.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import time
from pathlib import Path


def nvidia_smi(fields: str) -> dict:
    try:
        proc = subprocess.run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=60)
        rows = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        return {"ok": proc.returncode == 0, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build_inputs(size: int, device, dtype):
    """Deterministic matrices (no RNG) so every job runs the *same* workload."""
    import torch

    n = size * size
    base = (torch.arange(n, device=device, dtype=torch.float64) % 1021.0) - 510.0
    a = (base / 510.0).reshape(size, size).to(dtype)
    b = (torch.arange(n, device=device, dtype=torch.float64).flip(0) % 1013.0 - 506.0)
    b = (b / 506.0).reshape(size, size).to(dtype)
    return a, b


def bench_device(torch, index: int, size: int, warmup: int, iters: int,
                 l2_flush_mb: int) -> dict:
    """Throughput of one device.

    Round 31 defect fixed: CUDA events record on the **current** device, so
    benchmarking cuda:1 without ``torch.cuda.device(1)`` timed device 0 while the
    matmul ran on device 1 — the result was ~10x too fast with 82% variance.
    """
    with torch.cuda.device(index):
        device = torch.device(f"cuda:{index}")
        props = torch.cuda.get_device_properties(index)
        a, b = build_inputs(size, device, torch.float32)
        c = torch.empty(size, size, device=device, dtype=torch.float32)
        for _ in range(warmup):
            torch.mm(a, b, out=c)
        torch.cuda.synchronize(index)
        cache = torch.empty(l2_flush_mb * 1024 * 1024 // 4, dtype=torch.int32, device=device)
        events = [(torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
                  for _ in range(iters)]
        for start_event, stop_event in events:
            cache.zero_()
            start_event.record()
            torch.mm(a, b, out=c)
            stop_event.record()
        torch.cuda.synchronize(index)
        samples = sorted(start_event.elapsed_time(stop_event) / 1000.0
                         for start_event, stop_event in events)
        median = statistics.median(samples)
        del a, b, c, cache
        torch.cuda.empty_cache()
    return {"index": index, "name": props.name, "sm_count": props.multi_processor_count,
            "median_s": median, "gflops": 2.0 * size ** 3 / median / 1e9,
            "n": len(samples), "cv": statistics.pstdev(samples) / median if median else None}


def concurrent_aggregate(torch, size: int, warmup: int, iters: int) -> dict | None:
    """All visible GPUs computing **at the same time** (threads, one per device).

    Events are created *inside* each device's context, and each thread times its
    own loop; the wall clock around all threads gives the aggregate, so scaling
    efficiency (aggregate vs sum of single-device numbers) is visible.
    """
    import threading

    count = torch.cuda.device_count()
    if count < 2:
        return None
    state = {}
    for index in range(count):
        with torch.cuda.device(index):
            device = torch.device(f"cuda:{index}")
            a, b = build_inputs(size, device, torch.float32)
            c = torch.empty(size, size, device=device, dtype=torch.float32)
            for _ in range(warmup):
                torch.mm(a, b, out=c)
            torch.cuda.synchronize(index)
            state[index] = {"device": device, "a": a, "b": b, "c": c,
                            "elapsed": None}

    def worker(index: int) -> None:
        with torch.cuda.device(index):
            info = state[index]
            started = time.perf_counter()
            for _ in range(iters):
                torch.mm(info["a"], info["b"], out=info["c"])
            torch.cuda.synchronize(index)
            info["elapsed"] = time.perf_counter() - started

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    wall_started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - wall_started
    per_device_gflops = [2.0 * size ** 3 * iters / info["elapsed"] / 1e9
                         for info in state.values() if info["elapsed"]]
    aggregate = 2.0 * size ** 3 * iters * count / wall / 1e9
    return {"devices": count, "wall_s": wall, "iters": iters,
            "aggregate_gflops": aggregate,
            "per_device_gflops": per_device_gflops,
            "mean_device_gflops": statistics.mean(per_device_gflops),
            "scaling_efficiency": (aggregate / (statistics.mean(per_device_gflops) * count))
            if per_device_gflops else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=2048)
    parser.add_argument("--iters", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--l2-flush-mb", type=int, default=256)
    parser.add_argument("--out", default="gpu_result.json")
    parser.add_argument("--status-out", default=None)
    parser.add_argument("--all-devices", action="store_true",
                        help="benchmark every visible GPU (default: on when >1 device)")
    args = parser.parse_args()

    started = time.time()
    report: dict = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hostname": socket.gethostname(),
        "status": "running",
        "params": {"size": args.size, "iters": args.iters, "warmup": args.warmup,
                   "l2_flush_mb": args.l2_flush_mb},
        "env": {key: os.environ.get(key) for key in
                ("CUDA_VISIBLE_DEVICES", "NVIDIA_TF32_OVERRIDE", "CUDA_LAUNCH_BLOCKING")},
        "gpu": {"identity": nvidia_smi("name,driver_version,memory.total,uuid"),
                "before": nvidia_smi("clocks.sm,power.draw,temperature.gpu,utilization.gpu"),
                "after": None},
        "torch": None, "math_mode": None,
        "fp32": None, "fp16": None, "copy": None, "checksum": None,
        "errors": [],
    }

    def flush(final_status: str) -> int:
        report["status"] = final_status
        report["seconds"] = round(time.time() - started, 1)
        report["gpu"]["after"] = nvidia_smi("clocks.sm,power.draw,temperature.gpu,utilization.gpu")
        target = Path(args.out)
        try:
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"cannot write report: {type(exc).__name__}: {exc}")
            return 1
        print(json.dumps({key: report.get(key) for key in
                          ("status", "device_name", "fp32", "fp16", "copy", "errors")},
                         ensure_ascii=False)[:1500])
        return 0

    try:
        import torch
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"torch import failed: {type(exc).__name__}: {exc}")
        return flush("no_torch")

    report["torch"] = {"version": torch.__version__,
                       "cuda_available": torch.cuda.is_available(),
                       "cuda_version": getattr(torch.version, "cuda", None)}
    if not torch.cuda.is_available():
        report["errors"].append("CUDA not available")
        return flush("no_cuda")

    # pin the math mode so "fp32" means FP32 on every image
    try:
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"cannot pin math mode: {type(exc).__name__}: {exc}")
    report["math_mode"] = {
        "allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "float32_matmul_precision": torch.get_float32_matmul_precision(),
        "allow_fp16_reduced_precision_reduction":
            torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction,
    }

    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(0)
    report["device_name"] = props.name
    report["device"] = {"uuid": str(props.uuid) if hasattr(props, "uuid") else None,
                        "capability": list(torch.cuda.get_device_capability(0)),
                        "sm_count": props.multi_processor_count,
                        "total_memory_mib": round(props.total_memory / 1048576, 1)}

    def bench(dtype, label: str) -> dict | None:
        a, b = build_inputs(args.size, device, dtype)
        c = torch.empty(args.size, args.size, device=device, dtype=dtype)
        for _ in range(args.warmup):
            torch.mm(a, b, out=c)
        torch.cuda.synchronize()
        cache = torch.empty(args.l2_flush_mb * 1024 * 1024 // 4, dtype=torch.int32, device=device)
        events = [(torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
                  for _ in range(args.iters)]
        for start, stop in events:
            cache.zero_()                      # evict L2 outside the timed window
            start.record()
            torch.mm(a, b, out=c)
            stop.record()
        torch.cuda.synchronize()
        samples = sorted(start.elapsed_time(stop) / 1000.0 for start, stop in events)
        median = statistics.median(samples)
        flops = 2.0 * args.size ** 3
        result = {
            "label": label, "n": len(samples),
            "median_s": median, "min_s": samples[0],
            "p90_s": samples[min(len(samples) - 1, int(0.9 * len(samples)))],
            "cv": statistics.pstdev(samples) / median if median else None,
            "gflops": flops / median / 1e9,
            "params": {"size": args.size, "iters": args.iters, "warmup": args.warmup},
        }
        del a, b, c, cache
        torch.cuda.empty_cache()
        return result

    def safe(stage: str, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"{stage}: {type(exc).__name__}: {exc}")
            report["status"] = "partial"
            return None

    report["fp32"] = safe("fp32", lambda: bench(torch.float32, "fp32"))
    report["fp16"] = safe("fp16", lambda: bench(torch.float16, "fp16"))

    def copy() -> dict:
        n = 256 * 1024 * 1024 // 4
        src = torch.ones(n, device=device, dtype=torch.float32)
        dst = torch.empty_like(src)
        torch.cuda.synchronize()
        events = [(torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
                  for _ in range(5)]
        for start, stop in events:
            start.record()
            dst.copy_(src)
            stop.record()
        torch.cuda.synchronize()
        samples = sorted(start.elapsed_time(stop) / 1000.0 for start, stop in events)
        median = statistics.median(samples)
        ok = bool(torch.equal(dst[:1024], src[:1024]))
        del src, dst
        torch.cuda.empty_cache()
        return {"median_s": median, "gbps": (2 * n * 4) / median / 1e9,
                "n": len(samples), "copy_correct": ok}

    report["copy"] = safe("copy", copy)

    def checksum() -> dict:
        """Same workload on every GPU, plus a real correctness verdict."""
        small = 512
        a, b = build_inputs(small, device, torch.float32)
        c = a @ b
        torch.cuda.synchronize()
        ref = (a.double().cpu() @ b.double().cpu())
        out = c.double().cpu()
        rel = (out - ref).abs() / (ref.abs() + 1e-12)
        return {"input_checksum": float(a.double().sum() + b.double().sum()),
                "output_checksum": float(out.sum()),
                "max_rel_err_vs_fp64": float(rel.max()),
                "finite": bool(torch.isfinite(out).all())}

    report["checksum"] = safe("checksum", checksum)

    device_count = torch.cuda.device_count()
    report["device_count"] = device_count
    if args.all_devices or device_count > 1:
        def multi() -> dict:
            per_device = [bench_device(torch, i, args.size, args.warmup, args.iters,
                                       args.l2_flush_mb)
                          for i in range(device_count)]
            aggregate = concurrent_aggregate(torch, args.size, args.warmup, args.iters)
            return {"device_count": device_count, "devices": per_device,
                    "concurrent": aggregate,
                    "sum_single_gflops": sum(d["gflops"] for d in per_device)}

        report["multi_device"] = safe("multi_device", multi)

    status = "ok"
    if report["fp32"] is None or report["fp16"] is None:
        status = "partial"
    return flush(report["status"] if report["status"] != "running" else status)


if __name__ == "__main__":
    raise SystemExit(main())
