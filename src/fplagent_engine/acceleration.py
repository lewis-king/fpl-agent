from __future__ import annotations

import os
import warnings
from functools import lru_cache
from typing import Any

import numpy as np

ACCELERATOR_ENV = "FPLAGENT_ACCELERATOR"
GPU_MIN_MULTIPLIES_ENV = "FPLAGENT_GPU_MIN_MULTIPLIES"
POLICY_WORKERS_ENV = "FPLAGENT_POLICY_WORKERS"
ROLE_WORKERS_ENV = "FPLAGENT_ROLE_WORKERS"


def accelerator_preference() -> str:
    value = os.environ.get(ACCELERATOR_ENV, "auto").strip().lower()
    if value not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"{ACCELERATOR_ENV} must be one of auto, cpu or cuda")
    return value


def policy_worker_count() -> int:
    configured = os.environ.get(POLICY_WORKERS_ENV)
    if configured is not None:
        workers = int(configured)
        if workers < 1:
            raise ValueError(f"{POLICY_WORKERS_ENV} must be positive")
        return workers
    # MILP policies are independent and HiGHS is deliberately restricted to one
    # thread in each worker. Leave a few physical cores for CUDA feeding, HTTP and
    # the desktop rather than blindly occupying every SMT thread.
    logical_cpus = os.cpu_count() or 2
    return max(1, min(12, logical_cpus // 2))


def role_scenario_worker_count() -> int:
    configured = os.environ.get(ROLE_WORKERS_ENV)
    if configured is not None:
        workers = int(configured)
        if workers < 1:
            raise ValueError(f"{ROLE_WORKERS_ENV} must be positive")
        return workers
    # Four declared scenarios are independent. The role audit memory-maps their
    # large immutable simulation tensors into clean worker processes, bypassing
    # the GIL without multiplying the input-world memory footprint.
    return min(4, policy_worker_count())


def gpu_min_multiplies() -> int:
    # RTX 5090 benchmarks on the production shapes show that autosub construction
    # and PCIe transfer dominate below two billion weighted operations. Keep those
    # jobs on the faster CPU path unless an operator explicitly lowers the gate.
    return max(0, int(os.environ.get(GPU_MIN_MULTIPLIES_ENV, "2000000000")))


@lru_cache(maxsize=1)
def _cupy() -> Any | None:
    if accelerator_preference() == "cpu":
        return None
    try:
        import cupy as cp

        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError("no CUDA device is visible")
        # Force context creation here so failures occur before a long simulation.
        _ = cp.cuda.Device().compute_capability
        return cp
    except Exception as exc:
        if accelerator_preference() == "cuda":
            raise RuntimeError("CUDA acceleration was explicitly requested but is unavailable") from exc
        warnings.warn(f"CUDA acceleration unavailable; using CPU: {exc}", stacklevel=2)
        return None


def cuda_available() -> bool:
    return _cupy() is not None


def cupy_module() -> Any | None:
    """Return the lazily loaded CuPy module for engine-internal kernels."""

    return _cupy()


def cuda_device() -> dict[str, Any] | None:
    cp = _cupy()
    if cp is None:
        return None
    device = cp.cuda.Device()
    properties = cp.cuda.runtime.getDeviceProperties(device.id)
    name = properties["name"]
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    free, total = cp.cuda.runtime.memGetInfo()
    return {
        "backend": "cupy",
        "device_id": int(device.id),
        "name": str(name),
        "free_memory_bytes": int(free),
        "total_memory_bytes": int(total),
    }


def xgboost_infer(
    model: Any,
    matrix: np.ndarray,
    *,
    method: str = "predict",
) -> np.ndarray:
    """Run CUDA XGBoost inference without silently staging a CPU DMatrix.

    XGBoost's sklearn API accepts a CUDA array directly.  Supplying the normal
    NumPy feature matrix to a CUDA-trained booster triggers a slower DMatrix
    fallback and a host-to-device copy for every prediction call.
    """

    inference = getattr(model, method)
    cp = _cupy()
    if cp is None:
        return np.asarray(inference(matrix))
    try:
        result = inference(cp.asarray(matrix, dtype=cp.float32))
        if isinstance(result, cp.ndarray):
            result = cp.asnumpy(result)
        return np.asarray(result)
    except Exception as exc:
        if accelerator_preference() == "cuda":
            raise
        warnings.warn(
            f"CUDA XGBoost {method} failed; using CPU input fallback: {exc}",
            stacklevel=2,
        )
        return np.asarray(inference(matrix))


def use_cuda_for(*, multiply_count: int) -> bool:
    return multiply_count >= gpu_min_multiplies() and cuda_available()


def sparse_dense_matmul(
    left: Any,
    right: np.ndarray,
    *,
    label: str,
) -> tuple[np.ndarray, str]:
    """Multiply a CPU CSR matrix by a dense matrix using CUDA when worthwhile.

    FPL score matrices contain small integers and player-utility matrices use
    float32. CUDA float32 therefore preserves every integer score exactly while
    avoiding unsupported int8/int16 cuSPARSE combinations.
    """

    multiply_count = int(left.nnz) * int(right.shape[1] if right.ndim > 1 else 1)
    if not use_cuda_for(multiply_count=multiply_count):
        return np.asarray(left @ right), "cpu"

    cp = _cupy()
    assert cp is not None
    try:
        from cupyx.scipy import sparse as cupy_sparse

        gpu_left = cupy_sparse.csr_matrix(left.astype(np.float32, copy=False))
        gpu_right = cp.asarray(right, dtype=cp.float32)
        gpu_output = gpu_left @ gpu_right
        output = cp.asnumpy(gpu_output)
        cp.cuda.get_current_stream().synchronize()
        print(
            f"Acceleration: CUDA {label} ({left.shape[0]:,}x{left.shape[1]:,}, "
            f"{multiply_count:,} weighted multiplies)",
            flush=True,
        )
        return output, "cuda"
    except Exception as exc:
        if accelerator_preference() == "cuda":
            raise
        warnings.warn(f"CUDA {label} failed; using CPU: {exc}", stacklevel=2)
        return np.asarray(left @ right), "cpu-fallback"


def release_cuda_memory() -> None:
    cp = _cupy()
    if cp is None:
        return
    cp.cuda.get_current_stream().synchronize()
    cp.get_default_memory_pool().free_all_blocks()
    cp.get_default_pinned_memory_pool().free_all_blocks()
