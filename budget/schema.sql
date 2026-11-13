-- Schéma de données. Tous les montants sont en centimes (INTEGER).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    password_hash TEXT
);

-- Les comptes sont définis dans settings.toml et synchronisés au démarrage.
CREATE TABLE IF NOT EXISTS accounts (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name    TEXT NOT NULL,
    sort    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, name)
);

-- Un poste a une identité stable d'un mois à l'autre (pour l'historique).
CREATE TABLE IF NOT EXISTS postes (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    name           TEXT NOT NULL,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    category       TEXT NOT NULL DEFAULT 'besoins' CHECK (category IN ('besoins','envies','epargne')),
    debit_day      INTEGER CHECK (debit_day IS NULL OR debit_day BETWEEN 1 AND 31),
    seasonal       INTEGER NOT NULL DEFAULT 0,
    contractual    INTEGER NOT NULL DEFAULT 0,
    is_reserve     INTEGER NOT NULL DEFAULT 0,
    default_planned INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1,
    sort           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS months (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    salary_net    INTEGER,
    net_imposable INTEGER,
    pas           INTEGER,          -- prélèvement à la source
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, year, month)
);

-- Prévu et réel d'un poste pour un mois.
CREATE TABLE IF NOT EXISTS lines (
    id        INTEGER PRIMARY KEY,
    month_id  INTEGER NOT NULL REFERENCES months(id) ON DELETE CASCADE,
    poste_id  INTEGER NOT NULL REFERENCES postes(id),
    planned   INTEGER NOT NULL DEFAULT 0,
    actual    INTEGER,          -- NULL = pas encore saisi
    info_partner INTEGER,       -- part de Laetitia, à titre d'information
    UNIQUE (month_id, poste_id)
);

CREATE TABLE IF NOT EXISTS cheques (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    amount     INTEGER NOT NULL,
    payee      TEXT NOT NULL,
    year       INTEGER NOT NULL,
    month      INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    note       TEXT NOT NULL DEFAULT '',
    account_id INTEGER REFERENCES accounts(id),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','debited'))
);

-- Décisions de Fred sur les propositions d'ajustement (les propositions
-- elles-mêmes sont recalculées à la volée depuis l'historique).
CREATE TABLE IF NOT EXISTS proposal_decisions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    poste_id   INTEGER NOT NULL REFERENCES postes(id),
    ref_year   INTEGER NOT NULL,
    ref_month  INTEGER NOT NULL,
    current    INTEGER NOT NULL,
    proposed   INTEGER NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('accepted','refused')),
    decided_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (poste_id, ref_year, ref_month)
);

CREATE TABLE IF NOT EXISTS credits (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    name        TEXT NOT NULL,
    target_date TEXT,            -- AAAA-MM-JJ, optionnel
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS credit_balances (
    credit_id INTEGER NOT NULL REFERENCES credits(id) ON DELETE CASCADE,
    year      INTEGER NOT NULL,
    month     INTEGER NOT NULL,
    balance   INTEGER NOT NULL,
    PRIMARY KEY (credit_id, year, month)
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(ip, ts);
