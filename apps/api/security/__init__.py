"""Browser-tier security telemetry: the Content-Security-Policy violation collector.

This package holds the ONE unauthenticated, world-callable endpoint that exists to be
told about something rather than to be asked for something. See `csp_reports.py` for what
is kept out of a report and why, and `routes.py` for the admission control.
"""
