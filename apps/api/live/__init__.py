"""Live change notes (D-774): what changed, announced after commit, so open consoles
refetch without a page refresh.

`capture` records which topics a committed transaction touched, `publish` sends them to
Redis pub/sub, `hub` holds this process's one subscription, and `routes` serves them to
browsers as server-sent events. `topics` is the vocabulary and the table map.
"""
