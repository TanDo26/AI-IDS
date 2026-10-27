"""
Host metrics for the admin server-status page: CPU, RAM, data-volume disk, and GPU when present.
"""

from pathlib import Path

import psutil


def gpu_stats() -> list[dict]:
    try:
        import pynvml  # nvidia-ml-py; optional
    except ImportError:
        return []
    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError:
        return []
    try:
        gpus = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            gpus.append({
                "name": name.decode() if isinstance(name, bytes) else name,   # bytes in older nvidia-ml-py
                "utilization_percent": pynvml.nvmlDeviceGetUtilizationRates(handle).gpu,
                "memory_used_mb": memory.used // 2**20,
                "memory_total_mb": memory.total // 2**20,
            })
        return gpus
    finally:
        pynvml.nvmlShutdown()


def system_stats(data_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(data_dir))
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": memory.percent,
        "ram_used_mb": memory.used // 2**20,
        "ram_total_mb": memory.total // 2**20,
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 2**30, 1),
        "disk_total_gb": round(disk.total / 2**30, 1),
        "gpus": gpu_stats(),
    }
