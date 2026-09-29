"""Post-migration sanity checks.

TODO: extend CHECKS with anything specific (e.g. known
bad tourney_ids, players with implausible heights, etc).
"""
from db.connection import get_connection

CHECKS = {
    "players with zero matches": """
        SELECT COUNT(*) FROM players p
        WHERE NOT EXISTS (
            SELECT 1 FROM matches m WHERE m.winner_id = p.player_id OR m.loser_id = p.player_id
        )""",
    "duplicate matches (same tourney_id + match_num)": """
        SELECT tourney_id, match_num, COUNT(*) FROM matches
        GROUP BY tourney_id, match_num HAVING COUNT(*) > 1""",
    "rounds missing from round_order_map": """
        SELECT DISTINCT round FROM matches
        WHERE round NOT IN (SELECT round FROM round_order_map)""",
    "tournaments with invalid edition_year": """
        SELECT tourney_id FROM tournaments WHERE edition_year IS NULL OR edition_year < 1950""",
    "matches missing a participant row": """
        SELECT m.match_id FROM matches m
        WHERE (SELECT COUNT(*) FROM match_stats mp WHERE mp.match_id = m.match_id) < 2""",
    "implausible ranks": """
        SELECT COUNT(*) FROM match_stats WHERE rank_at_match < 1 OR rank_at_match > 3000""",
}


def main() -> None:
    conn = get_connection()
    any_failed = False
    for name, query in CHECKS.items():
        rows = conn.execute(query).fetchall()
        ok = not rows or list(rows[0]) == [0]
        print(f"[{'OK' if ok else 'FAIL'}] {name}")
        if not ok:
            any_failed = True
            for r in rows[:10]:
                print("   ", tuple(r))
    conn.close()
    if any_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
