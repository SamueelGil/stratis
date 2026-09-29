import re

def normalize_name(name:str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[.\-']", "", name)
    return re.sub(r"\s+", " ", name)


"""
TODO: run this against migrated `players` table and manually
    inspect the results before trusting Elo/h2h numbers. If any
    real duplicates are found, resolve them by picking a canonical player_id and
    inserting the alias into `player_aliases` — then re-run the
    migration with the alias table consulted.
"""
def find_potential_duplicates(conn) -> list[tuple[str, list[int]]]:
    rows = conn.execute("SELECT player_id, full_name FROM players").fetchall()
    buckets: dict[str, list[int]] = {}
    for row in rows:
        key = normalize_name(row["full_name"])
        buckets.setdefault(key, []).append(row["player_id"])
    return [(name, ids) for name, ids in buckets.items() if len(ids) > 1]
