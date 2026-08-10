"""Cross-cutting machinery shared by every FastAPI deployable.

Nothing in here knows about a domain (no leads, no calls, no agents) — domain modules
import FROM core, never the other way round. That one-way rule is what lets
voice-runtime reuse the bootstrap without dragging the monolith onto the voice path.
"""
