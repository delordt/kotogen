"""The Anki adapter: the one part of kotogen that knows Anki exists.

The library makes cards and stops at a file; whatever reaches into a collection
lives here. Only the command line and the menu import it, a line
`tests/test_boundary.py` holds, and it needs nothing beyond the standard
library: AnkiConnect is spoken over HTTP.
"""
