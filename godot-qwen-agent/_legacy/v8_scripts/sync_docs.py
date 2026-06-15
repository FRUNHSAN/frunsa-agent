#!/usr/bin/env python3
"""Doc-as-Code: sync CLAUDE.md from config/relational_params.py.

Reads the single source of truth and auto-renders the PLAN2 Golden
Parameters section in CLAUDE.md. Run after changing any param.

Usage: python scripts/sync_docs.py
"""

from __future__ import annotations
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.relational_params import PARAMS

CLAUDE_PATH = Path(__file__).resolve().parent.parent / "CLAUDE.md"
MARKER_START = "## PLAN2 Golden Parameters (from blind test, 2026-05-29)"
MARKER_END = "## PLAN2/3/4 Architectural Invariants"

TEMPLATE = """## PLAN2 Golden Parameters (from blind test, 2026-05-29)

These thresholds were calibrated against a real human subject who was unaware of PLAN2. The subject reported the system "听得进去" (listens and understands) — confirming the relational adaptation was perceptible and positive.

### Fatigue Detection
- **Trigger keywords**: "好累" (tired), "简单" (simple/brief) — single input containing both
- **Energy transition**: NEUTRAL -> LOW on the exact round containing fatigue keywords
- **Energy persistence**: LOW maintained across subsequent rounds (does not snap back)
- **Response compression**: {fatigue_pct:.0%} reduction perceived as "listening", not as "broken"

### Trust Dynamics
- **Asymmetric EMA**: negative signals alpha={neg_alpha:.2f}, positive signals alpha={pos_alpha:.2f}
- **Trust stability**: no erosion during adaptation when intentional violation is perceived as agency
- **Key finding**: INTENTIONAL_VIOLATION for fatigue did NOT reduce perceived trust. The user attributed the change to the agent's agency ("it listens"), not to a system failure.

### Bayesian Engine Parameters
- **Variance decay gamma**: {decay_gamma:.2f} (each calm round shrinks variance by {decay_pct:.0%})
- **Variance floor**: {var_floor:.2f} (prevents infinite certainty)
- **Uncertain threshold**: {uncertain:.2f} (above this -> conservative mode)
- **Peace threshold**: {peace} rounds (then baseline drift activates at +{drift}/round toward {target})
- **Energy confirm window**: {confirm} rounds (prevents false fatigue snap)
- **Renegotiation trust threshold**: {reneg_trust:.2f} (calibrated from blind test, was 0.7)

### Design Implications for PLAN3
- `RelationalEvaluator` keyword heuristics are sufficient for Level 1 fatigue detection (Chinese + English)
- Response compression ratio should target ~{fatigue_pct:.0%} reduction for LOW energy mode
- Trust gating for RenegotiationWatcher ({reneg_trust:.2f} threshold) calibrated from blind test — real trust builds slowly
- EmbodiedReflex should NOT announce "I detected fatigue" — the subject felt the adaptation was natural, not mechanical
"""


def main():
    content = CLAUDE_PATH.read_text(encoding="utf-8")

    rendered = TEMPLATE.format(
        fatigue_pct=PARAMS.fatigue_response_compression,
        neg_alpha=PARAMS.trust_alpha_negative,
        pos_alpha=PARAMS.trust_alpha_positive,
        decay_gamma=PARAMS.variance_decay_gamma,
        decay_pct=1 - PARAMS.variance_decay_gamma,
        var_floor=PARAMS.variance_floor,
        uncertain=PARAMS.uncertain_threshold,
        peace=PARAMS.peace_threshold,
        drift=PARAMS.drift_rate,
        target=PARAMS.drift_target,
        confirm=PARAMS.energy_confirm_window,
        reneg_trust=PARAMS.renegotiation_trust_threshold,
    )

    # Replace section between markers
    pattern = re.compile(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
        re.DOTALL,
    )
    if not pattern.search(content):
        print("ERROR: Could not find markers in CLAUDE.md")
        sys.exit(1)

    new_content = pattern.sub(rendered + "\n\n" + MARKER_END, content)
    CLAUDE_PATH.write_text(new_content, encoding="utf-8")
    print(f"Synced: config/relational_params.py -> CLAUDE.md")
    print(f"  Params: alpha(-)={PARAMS.trust_alpha_negative}, alpha(+)={PARAMS.trust_alpha_positive}")
    print(f"  Decay: gamma={PARAMS.variance_decay_gamma}, floor={PARAMS.variance_floor}")
    print(f"  Drift: peace={PARAMS.peace_threshold}, rate={PARAMS.drift_rate}, target={PARAMS.drift_target}")


if __name__ == "__main__":
    main()
