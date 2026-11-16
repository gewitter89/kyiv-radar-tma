-- Kyiv Radar Database Schema (SQLite)
-- Database file: /opt/resell-radar-ukraine/data/rent_deals.db

CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    details TEXT,
    reporter_info TEXT,
    status TEXT DEFAULT 'pending_review',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS landlord_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    price TEXT NOT NULL,
    rooms INTEGER NOT NULL,
    phone TEXT NOT NULL,
    gpon INTEGER DEFAULT 0,
    generator INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending_review',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    moderator_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_complaints_deal_id ON complaints(deal_id);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_landlords_status ON landlord_submissions(status);
