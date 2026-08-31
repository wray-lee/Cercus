#!/usr/bin/env python3
"""Coverage report script for critical paths.

Verifies test coverage meets thresholds:
- src/core/kinematics.py: ≥85%
- src/core/hardware.py: ≥75%
- src/workers/stimulus_worker.py: ≥70%
"""
import subprocess
import sys
import re

THRESHOLDS = {
    'src/core/kinematics.py': 85,
    'src/core/hardware.py': 75,
    'src/workers/stimulus_worker.py': 70,
}

def main() -> None:
    cmd = [
        sys.executable, '-m', 'pytest',
        '--cov=src.core.kinematics',
        '--cov=src.core.hardware',
        '--cov=src.workers.stimulus_worker',
        '--cov-report=term-missing',
        '-q'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stdout + result.stderr

    # Parse coverage percentages
    coverage = {}
    for line in output.split('\n'):
        for module in THRESHOLDS:
            # Match module path with backslash (Windows) or forward slash
            module_pattern = module.replace('/', r'[/\\]')
            if re.search(module_pattern, line):
                match = re.search(r'(\d+)%', line)
                if match:
                    coverage[module] = int(match.group(1))

    # Check thresholds
    failures = []
    for module, threshold in THRESHOLDS.items():
        actual = coverage.get(module, 0)
        if actual < threshold:
            failures.append(f"{module}: {actual}% < {threshold}%")
        else:
            print(f"[PASS] {module}: {actual}% (>={threshold}%)")

    if failures:
        print("\n[FAIL] Coverage threshold failures:")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("\n[PASS] All coverage thresholds met")
        sys.exit(0)

if __name__ == '__main__':
    main()
