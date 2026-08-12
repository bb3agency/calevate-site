"""Lead ingest — external sources pushing leads at us (FLOWS §4).

The module boundary matters here more than usual: this is the ONE surface where an
unauthenticated third party (a form vendor, Meta's webhook infrastructure, a Zapier
zap someone configured) sends us data that can end in a real phone ringing. Everything
in this module is therefore built around two questions — "is this sender who the
config says it is?" and "is dialling this number lawful right now?" — and the second
one is always answered by the compliance gate, never locally.
"""
