"""Phase 2a library tests for minyoung-mah.

These tests exercise the six-protocol library surface in isolation from
any specific application (coding, apt-legal). They use in-memory SQLite,
a fake chat model, and the :class:`CollectingObserver` so nothing touches
the network.
"""
