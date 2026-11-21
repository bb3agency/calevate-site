"""How a platform prompt names the business it writes for, without assuming its size or trade.

Clients range from a one-person shop to a college, a hospital chain or an NBFC's calling
desk. A prompt that says "a small business" pulls every model towards shop-scale wording,
so every platform prompt names the business through these constants instead of typing its
own phrase. India is right: the product serves Indian numbers only.
"""

from __future__ import annotations

from typing import Final

#: The noun phrase, for "one ...", "the ...", "this ...".
BUSINESS_KIND: Final = "Indian business"
#: With its article. The article is written for `BUSINESS_KIND`'s first sound, so the two
#: change together.
BUSINESS_FRAME: Final = f"an {BUSINESS_KIND}"
#: The plural, for the platform describing itself.
BUSINESSES_FRAME: Final = "Indian businesses"

__all__ = ["BUSINESSES_FRAME", "BUSINESS_FRAME", "BUSINESS_KIND"]
