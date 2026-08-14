"""Per-tenant feature flags (SURFACES §1) — plain config rows, never a flag SaaS.

`registry.py` declares them, `service.py` resolves them, `routes.py` is the admin
surface that reads and flips them. Nothing else in `apps/` reads a flag yet, and that
is deliberate — see `registry.py` on why introducing the mechanism and rewiring an
existing feature are two changes.
"""
