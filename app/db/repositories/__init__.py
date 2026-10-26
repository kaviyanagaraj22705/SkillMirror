"""Thin per-aggregate repositories (spec §10.4).

Each module exposes functions that take a connection plus typed arguments and
return models. Repositories never import each other; joins live in the reader.
"""
