from __future__ import annotations

import hashlib
import json
import math
import platform
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "python" / "src"))

from comtus_ai.models import EvidenceSource  # noqa: E402
from comtus_ai.optimizer import Opponent, Pitcher, optimize_rotation  # noqa: E402


def run_case() -> dict[str, object]:
    pitchers = [Pitcher(f"p{i}", f"Pitcher {i}") for i in range(5)]
    opponents = [Opponent(f"o{i}", f"Opponent {i}") for i in range(5)]
    scores = {
        (pitcher.card_id, opponent.opponent_id): float((p_index * 7 + o_index * 11) % 23)
        for p_index, pitcher in enumerate(pitchers)
        for o_index, opponent in enumerate(opponents)
    }
    return optimize_rotation(pitchers, opponents, scores, input_source=EvidenceSource.SYNTHETIC_TEST).to_dict(pitchers, opponents)


def percentile_nearest_rank(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def machine_model() -> str | None:
    if platform.system() != "Darwin":
        return None
    try:
        return subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    warmups = 5
    iterations = 50
    expected = run_case()
    for _ in range(warmups):
        if run_case() != expected:
            raise RuntimeError("warm-up output differed from the reference result")
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        actual = run_case()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if actual != expected:
            raise RuntimeError("benchmark output differed from the reference result")
        samples_ms.append(elapsed)
    stable_json = json.dumps(expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    print(json.dumps({
        "benchmark": "synthetic_5x5_rotation_optimizer",
        "scope": "python heuristic CPU only; excludes game capture and OCR",
        "status": "EXEC_PASS",
        "iterations": iterations,
        "warmups": warmups,
        "output_sha256": hashlib.sha256(stable_json).hexdigest(),
        "output_equivalent": True,
        "median_ms": round(statistics.median(samples_ms), 4),
        "p95_ms": round(percentile_nearest_rank(samples_ms, 0.95), 4),
        "min_ms": round(min(samples_ms), 4),
        "max_ms": round(max(samples_ms), 4),
        "architecture": platform.machine(),
        "machine_model": machine_model(),
        "macos": platform.mac_ver()[0] or None,
        "python": platform.python_version(),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
