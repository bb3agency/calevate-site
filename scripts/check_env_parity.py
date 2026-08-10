"""Guardrail: .env.example ⟷ Settings parity, both directions
(ENGINEERING-PRACTICES §2; fail-fast config doctrine, DEV-SETUP §4).

Every key in .env.example must be a Settings field, and every Settings field must
appear in .env.example — config drift fails CI, not production boot.

Run: uv run python -m scripts.check_env_parity
"""

import re
import sys
from pathlib import Path

from calevate_shared.config import Settings


def main() -> int:
    example = Path(__file__).resolve().parent.parent / ".env.example"
    example_keys = {
        m.group(1).lower()
        for line in example.read_text(encoding="utf-8").splitlines()
        if (m := re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip()))
    }
    settings_keys = set(Settings.model_fields)

    only_example = sorted(example_keys - settings_keys)
    only_settings = sorted(settings_keys - example_keys)

    if only_example or only_settings:
        print("ENV PARITY: FAIL")
        if only_example:
            print(f"  in .env.example but not Settings: {only_example}")
        if only_settings:
            print(f"  in Settings but not .env.example: {only_settings}")
        return 1
    print(f"ENV PARITY: OK ({len(settings_keys)} keys aligned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
