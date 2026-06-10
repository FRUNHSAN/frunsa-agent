"""V7.5 Entropy Monitor — active concern via sublevel set filtration.

Exports:
  KernelStateSnapshot — frozen snapshot of Track C state at session end
  EntropyReading      — sampled internal tension
  EntropyMonitor      — g: (x_internal, identity) → S_int (pure function)
"""
from core.watcher.entropy_monitor import (
    KernelStateSnapshot,
    EntropyReading,
    EntropyMonitor,
)
