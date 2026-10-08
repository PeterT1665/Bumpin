-- BumpIn schema. Matches docs/CONTRACT.md section 2.
-- Timestamps are ISO 8601 strings. *_json columns hold JSON text.

CREATE TABLE IF NOT EXISTS festival (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    sim_today TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY,
    stage_id INTEGER REFERENCES stages(id),          -- NULL means shared pool
    canonical_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity_total INTEGER NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    manager_name TEXT,
    manager_email TEXT,
    stage_id INTEGER REFERENCES stages(id),
    set_start TEXT,
    set_end TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress',
    hospitality_cap REAL
);

CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,                               -- food, beverage, merch, other
    contact_name TEXT,
    contact_email TEXT,
    uses_gas INTEGER NOT NULL DEFAULT 0,
    site_zone TEXT,
    load_in_start TEXT,
    load_in_end TEXT,
    status TEXT NOT NULL DEFAULT 'in_progress'        -- in_progress, completed, rejected
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL,                         -- artist or vendor
    owner_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                               -- rider, permit, food_safety, insurance, gas, other
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    extracted_text TEXT,
    expiry_date TEXT,
    issuer TEXT,
    received_at TEXT NOT NULL,
    email_id INTEGER REFERENCES emails(id)
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY,
    direction TEXT NOT NULL,                          -- in or out
    from_addr TEXT,
    to_addr TEXT,
    subject TEXT,
    body TEXT,
    thread_id TEXT,
    received_at TEXT NOT NULL,
    classification TEXT,
    confidence REAL,
    is_major_change INTEGER NOT NULL DEFAULT 0,
    ticket_id INTEGER REFERENCES tickets(id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,                               -- rider_needs, vendor_eligibility, help
    owner_type TEXT,
    owner_id INTEGER,
    status TEXT NOT NULL DEFAULT 'open',
    severity TEXT,
    summary TEXT,
    proposed_actions_json TEXT,
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,                           -- conflict, warning, info
    message TEXT NOT NULL,
    suggestion TEXT,
    doc_id INTEGER REFERENCES documents(id),
    quote TEXT,
    page INTEGER,
    bbox_json TEXT,
    status TEXT NOT NULL DEFAULT 'open'               -- open, ignored, resolved
);

CREATE TABLE IF NOT EXISTS rider_items (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    doc_id INTEGER REFERENCES documents(id),
    raw_text TEXT,
    quote TEXT,
    page INTEGER,
    category TEXT NOT NULL,                           -- technical or hospitality
    inventory_item_id INTEGER REFERENCES inventory_items(id),
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_cost REAL,
    match_confidence REAL
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    inventory_item_id INTEGER NOT NULL REFERENCES inventory_items(id),
    quantity INTEGER NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'reserved'           -- reserved or released
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(id),
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    context_used_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',             -- draft, sent, failed
    created_by TEXT,
    approved_by TEXT,
    sent_at TEXT,
    mode TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(id),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    for_user TEXT NOT NULL,
    ticket_id INTEGER REFERENCES tickets(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0
);

-- Files Ravi uploads that are not equipment lists: kept as context for the AI.
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT,
    summary TEXT,
    uploaded_at TEXT NOT NULL
);
