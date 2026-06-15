"""Repository layer.

All database access goes through repository classes defined in this package.
Route handlers and services must **not** contain raw SQL or direct ORM queries;
they call repository methods instead.
"""
