"""Entity-resolution transform for Google-anchored restaurant matching.

The service builds candidate pairs for Google x Tripadvisor and Google x TheFork,
scores them, and writes auditable candidate decisions to MongoDB.
"""
