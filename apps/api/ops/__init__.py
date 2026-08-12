"""Operator surface: the switches an incident runbook reaches for.

Everything here is admin-realm, `ops:manage`, audit-logged, and NEVER load-shed —
the operator must not be able to lock themselves out of the controls they need
precisely when the platform is unhealthy (BACKEND-PATTERNS §6).
"""
