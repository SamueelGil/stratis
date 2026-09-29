import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from db.connection import get_connection, init_schema, PROJECT_ROOT
from ingestion.name_normalizer import normalize_name

CSV_PATH = PROJECT_ROOT / "data" / "tennis_data.csv"

ROUND_ORDER = {
    "Q1": -4, "Q2": -3, "Q3": -2, "Q4": -1,
    "ER": -5,
    "RR": 0,
    "R128": 1, "R64": 2, "R32": 3, "R16": 4,
    "QF": 5, "SF": 6, "BR": 6, "F": 7,
}

EXCLUDED_TOURNEY_LEVELS = {"D"}  # Davis Cup — team event, excluded


def _clean(value):
    """NaN is NOT the same as SQL NULL once it
    reaches sqlite3 — This converts NaN/None uniformly to
    Python None, which sqlite3 binds as a proper NULL."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _clean_int(value):
    v = _clean(value)
    if v is None:
        return None
    return int(v)


def _clean_str(value):
    v = _clean(value)
    return str(v) if v is not None else None

def _clean_hand(value) -> str:
    v = _clean_str(value)
    if v is None:
        return "U"
    v = v.strip().upper()
    return v if v in ("L", "R", "A") else "U"

def _parse_status(score) -> str:
    score = _clean_str(score)
    if not score:
        return "completed"
    s = score.upper()
    if "W/O" in s or s.strip() == "WO":
        return "walkover"
    if "RET" in s:
        return "retired"
    if "DEF" in s:
        return "disqualified"
    return "completed"


def _yyyymmdd_to_date(value) -> str:
    return datetime.strptime(str(int(value)), "%Y%m%d").strftime("%Y-%m-%d")


def _slug(name: str) -> str:
    s = normalize_name(name)
    return re.sub(r"\s+", "-", s)


def _iter_progress(rows, total: int, width: int = 40):
    if total <= 0:
        yield from rows
        return

    for i, row in enumerate(rows, start=1):
        filled = int(width * i / total)
        bar = "#" * filled + "-" * (width - filled)
        percent = (i / total) * 100
        sys.stdout.write(f"\r[{bar}] {i}/{total} ({percent:5.1f}%)")
        sys.stdout.flush()
        yield row

    sys.stdout.write("\n")
    sys.stdout.flush()


def _upsert_player(conn, player_id, name, hand, height_cm, country):
    conn.execute("""
        INSERT INTO players (player_id, full_name, hand, height_cm, country)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            full_name = excluded.full_name,
            hand = COALESCE(excluded.hand, players.hand),
            height_cm = COALESCE(excluded.height_cm, players.height_cm),
            country = COALESCE(excluded.country, players.country)
    """, (
        _clean_int(player_id), _clean_str(name),
        _clean_hand(hand), _clean_int(height_cm), _clean_str(country)
    ))


def _insert_match_and_stats(conn, row, match_id: int, tourney_id: str, match_num: int) -> None:
    status = _parse_status(getattr(row, "score", None))

    conn.execute("""
        INSERT INTO matches
        (match_id, tourney_id, match_num, round, winner_id, loser_id,
         score, best_of, minutes, status)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        match_id, tourney_id, match_num, row.round,
        _clean_int(row.winner_id), _clean_int(row.loser_id),
        _clean_str(getattr(row, "score", None)), _clean_int(getattr(row, "best_of", None)),
        _clean_int(getattr(row, "minutes", None)), status
    ))

    for is_winner, prefix, player_id in (
        (1, "winner", _clean_int(row.winner_id)),
        (0, "loser", _clean_int(row.loser_id)),
    ):
        stat_prefix = "w" if is_winner else "l"
        conn.execute("""
            INSERT INTO match_stats
            (match_id, player_id, is_winner, seed, entry, age_at_match,
             rank_at_match, rank_points_at_match, aces, double_faults,
             serve_points, first_serve_in, first_serve_won, second_serve_won,
             serve_games, bp_saved, bp_faced)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            match_id, player_id, is_winner,
            _clean_int(getattr(row, f"{prefix}_seed", None)),
            _clean_str(getattr(row, f"{prefix}_entry", None)),
            _clean(getattr(row, f"{prefix}_age", None)),
            _clean_int(getattr(row, f"{prefix}_rank", None)),
            _clean_int(getattr(row, f"{prefix}_rank_points", None)),
            _clean_int(getattr(row, f"{stat_prefix}_ace", None)),
            _clean_int(getattr(row, f"{stat_prefix}_df", None)),
            _clean_int(getattr(row, f"{stat_prefix}_svpt", None)),
            _clean_int(getattr(row, f"{stat_prefix}_1stIn", None)),
            _clean_int(getattr(row, f"{stat_prefix}_1stWon", None)),
            _clean_int(getattr(row, f"{stat_prefix}_2ndWon", None)),
            _clean_int(getattr(row, f"{stat_prefix}_SvGms", None)),
            _clean_int(getattr(row, f"{stat_prefix}_bpSaved", None)),
            _clean_int(getattr(row, f"{stat_prefix}_bpFaced", None)),
        ))


def main() -> None:
    conn = get_connection()
    init_schema(conn)

    for round_name, order in ROUND_ORDER.items():
        conn.execute(
            "INSERT OR IGNORE INTO round_order_map (round, round_order) VALUES (?, ?)",
            (round_name, order)
        )

    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()

    required = {"tourney_name", "surface", "tourney_level", "tourney_date",
                "winner_id", "winner_name", "loser_id", "loser_name",
                "score", "best_of", "round"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing expected columns: {missing}")

    before = len(df)
    df = df[~df["tourney_level"].isin(EXCLUDED_TOURNEY_LEVELS)]
    print(f"Excluded {before - len(df)} rows from excluded tourney levels "
          f"({EXCLUDED_TOURNEY_LEVELS}); {len(df)} remaining.")

    unknown_rounds = set(df["round"].dropna().unique()) - set(ROUND_ORDER.keys())
    if unknown_rounds:
        raise ValueError(
            f"Unmapped rounds found — add these to ROUND_ORDER before continuing: {unknown_rounds}"
        )

    df["_round_order"] = df["round"].map(ROUND_ORDER)
    df = df.sort_values(
        by=["tourney_date", "tourney_name", "_round_order"],
        ascending=[True, True, True],
        kind="stable"
    ).drop(columns=["_round_order"])

    tourneys_seen: set[str] = set()
    match_num_counters: dict[str, int] = {}
    match_id = 1
    skipped_self_matches = 0 

    conn.execute("BEGIN")
    try:
        for row in _iter_progress(df.itertuples(index=False), total=len(df)):
            winner_id = _clean_int(row.winner_id)
            loser_id = _clean_int(row.loser_id)

            # Dirty-data guard: a handful of rows in large historical
            # datasets have winner_id == loser_id
            if winner_id == loser_id:
                skipped_self_matches += 1
                continue

            tourney_date_str = _yyyymmdd_to_date(row.tourney_date)
            tourney_name = _clean_str(row.tourney_name) or "unknown"
            tourney_id = f"{int(row.tourney_date)}-{_slug(tourney_name)}"

            if tourney_id not in tourneys_seen:
                tourneys_seen.add(tourney_id)
                conn.execute("""
                    INSERT OR IGNORE INTO tournaments
                    (tourney_id, tourney_base_id, edition_year, tourney_name,
                     surface, draw_size, tourney_level, tourney_date)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    tourney_id, _slug(tourney_name), int(str(int(row.tourney_date))[:4]),
                    tourney_name, _clean_str(row.surface),
                    _clean_int(getattr(row, "draw_size", None)),
                    _clean_str(row.tourney_level), tourney_date_str
                ))

            _upsert_player(conn, row.winner_id, row.winner_name,
                            getattr(row, "winner_hand", None),
                            getattr(row, "winner_ht", None),
                            getattr(row, "winner_ioc", None))
            _upsert_player(conn, row.loser_id, row.loser_name,
                            getattr(row, "loser_hand", None),
                            getattr(row, "loser_ht", None),
                            getattr(row, "loser_ioc", None))

            match_num_counters[tourney_id] = match_num_counters.get(tourney_id, 0) + 1
            _insert_match_and_stats(conn, row, match_id, tourney_id, match_num_counters[tourney_id])
            match_id += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Migration complete: {match_id - 1} matches inserted.")
    if skipped_self_matches:
        print(f"Skipped {skipped_self_matches} rows with winner_id == loser_id (bad source data).")
    print("Now run: st-validate")

if __name__ == "__main__":
    main()