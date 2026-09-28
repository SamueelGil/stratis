-- ============================================================
-- SCHEMA — sistema de previsão de ténis (SQLite), v3
-- ============================================================


CREATE TABLE IF NOT EXISTS matches (
    match_id       INTEGER PRIMARY KEY,
    tourney_id     TEXT NOT NULL REFERENCES tournaments(tourney_id),
    match_num      INTEGER NOT NULL,
    round          TEXT NOT NULL REFERENCES round_order_map(round),
    winner_id      INTEGER NOT NULL REFERENCES players(player_id),
    loser_id       INTEGER NOT NULL REFERENCES players(player_id),
    score          TEXT,
    best_of        INTEGER,
    minutes        INTEGER,
    status         TEXT NOT NULL DEFAULT 'completed'
                   CHECK (status IN ('completed', 'retired', 'walkover', 'disqualified')),
    CHECK (winner_id != loser_id),
    UNIQUE (tourney_id, match_num)
);

CREATE TABLE IF NOT EXISTS players(
    player_id       INTEGER PRIMARY KEY,
    full_name       TEXT NOT NULL,
    hand            TEXT CHECK(hand IN ('L', 'R','U', 'A')),
    height_cm       INTEGER,
    country         TEXT
);

CREATE TABLE IF NOT EXISTS player_aliases(
    alias           TEXT PRIMARY KEY,
    player_id       INTEGER NOT NULL REFERENCES players(player_id)
);

CREATE TABLE IF NOT EXISTS tournaments(
    tourney_id      TEXT PRIMARY KEY,
    tourney_base_id TEXT NOT NULL,
    edition_year    INTEGER NOT NULL,
    tourney_name    TEXT NOT NULL,
    surface         TEXT CHECK(surface IN ('Clay', 'Hard', 'Grass', 'Carpet')),
    draw_size       INTEGER,
    tourney_level   TEXT,
    tourney_date    DATE NOT NULL
);


CREATE TABLE IF NOT EXISTS round_order_map(
    round           TEXT PRIMARY KEY,
    round_order     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS match_stats (
    match_id                INTEGER NOT NULL REFERENCES matches(match_id),
    player_id               INTEGER NOT NULL REFERENCES players(player_id),
    is_winner               INTEGER NOT NULL CHECK(is_winner IN (0,1)),
    seed                    INTEGER,
    entry                   TEXT,
    age_at_match            REAL,
    rank_at_match           INTEGER,
    rank_points_at_match    INTEGER,
    aces                    INTEGER,
    double_faults           INTEGER,
    serve_points            INTEGER,
    first_serve_in          INTEGER,
    first_serve_won         INTEGER,
    second_serve_won        INTEGER,
    serve_games             INTEGER,
    bp_saved                INTEGER,
    bp_faced                INTEGER,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS player_snapshots(
    snapshot_id         INTEGER PRIMARY KEY,
    pipeline_version    TEXT NOT NULL,
    player_id           INTEGER NOT NULL REFERENCES players(player_id),
    as_of_date          DATE NOT NULL,
    as_of_round_order   INTEGER NOT NULL,
    as_of_match_num     INTEGER NOT NULL,
    triggering_match_id INTEGER REFERENCES matches(match_id),
    elo_overall         REAL,
    elo_hard            REAL,
    elo_clay            REAL,
    elo_grass           REAL,
    elo_rating_deviation REAL,
    matches_last_10     INTEGER,
    win_rate_last_10    REAL,
    win_rate_last_10_surface REAL,
    avg_aces_last_10    REAL,
    avg_first_serve_pct_last10 REAL,
    matches_last_14_days INTEGER,
    days_since_last_match INTEGER,
    last_known_rank     INTEGER,
    last_known_rank_points INTEGER
);

CREATE TABLE IF NOT EXISTS training_examples(
    match_id             INTEGER PRIMARY KEY REFERENCES matches(match_id),
    pipeline_version      TEXT NOT NULL,
    player_a_id           INTEGER NOT NULL,
    player_b_id           INTEGER NOT NULL,
    elo_overall_a REAL, elo_overall_b REAL,
    elo_surface_a REAL, elo_surface_b REAL,
    elo_rd_a REAL, elo_rd_b REAL,
    win_rate_last10_a REAL, win_rate_last10_b REAL,
    avg_aces_last10_a REAL, avg_aces_last10_b REAL,
    rank_a INTEGER, rank_b INTEGER,
    days_since_last_match_a INTEGER, days_since_last_match_b INTEGER,
    h2h_wins_a INTEGER,
    h2h_wins_b INTEGER,
    surface TEXT,
    best_of INTEGER,
    tourney_level TEXT,
    label_a_wins INTEGER NOT NULL CHECK (label_a_wins IN (0, 1)),
    sample_weight REAL NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_tournaments_base ON tournaments(tourney_base_id, edition_year);

CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner_id);

CREATE INDEX IF NOT EXISTS idx_matches_loser ON matches(loser_id);

CREATE INDEX IF NOT EXISTS idx_matches_tourney ON matches(tourney_id);

CREATE INDEX IF NOT EXISTS idx_participants_player ON match_stats(player_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_player_version_order ON player_snapshots(player_id, pipeline_version, 
                                        as_of_date DESC, as_of_round_order DESC, as_of_match_num DESC);

CREATE INDEX IF NOT EXISTS idx_training_version ON training_examples(pipeline_version);


CREATE VIEW IF NOT EXISTS player_latest_snapshot AS
SELECT s.*
FROM player_snapshots s
INNER JOIN (
    SELECT player_id, pipeline_version, MAX(as_of_date || '-' || printf('%03d', as_of_round_order) || '-' || printf('%05d', as_of_match_num)) AS max_key
    FROM player_snapshots
    WHERE pipeline_version = (SELECT MAX(pipeline_version) FROM player_snapshots)
    GROUP BY player_id, pipeline_version
) latest
ON s.player_id = latest.player_id
    AND s.pipeline_version = latest.pipeline_version
    AND (s.as_of_date || '-' || printf('%03d', s.as_of_round_order) || '-' || printf('%05d', s.as_of_match_num)) = latest.max_key;


-- Query canónica de ordenação cronológica:
--
-- SELECT m.*, t.tourney_date, t.surface, t.tourney_level, ro.round_order
-- FROM matches m
-- JOIN tournaments t ON t.tourney_id = m.tourney_id
-- JOIN round_order_map ro ON ro.round = m.round
-- ORDER BY t.tourney_date, ro.round_order, m.match_num;


-- Query partilhada de head-to-head 
--
-- SELECT
--     SUM(CASE WHEN m.winner_id = :player_a THEN 1 ELSE 0 END) AS wins_a,
--     SUM(CASE WHEN m.winner_id = :player_b THEN 1 ELSE 0 END) AS wins_b
-- FROM matches m
-- JOIN tournaments t ON t.tourney_id = m.tourney_id
-- WHERE ((m.winner_id = :player_a AND m.loser_id = :player_b)
--     OR (m.winner_id = :player_b AND m.loser_id = :player_a))
--   AND t.tourney_date < :as_of_date
--   AND m.status = 'completed';