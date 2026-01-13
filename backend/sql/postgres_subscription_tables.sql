-- Reference schema requested (UUID-based).
-- NOTE: This repo currently uses integer IDs in SQLAlchemy models/migrations.
-- Keep this file as a Postgres reference for future re-platforming.

-- Users Table
CREATE TABLE users (
    id UUID PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Subscription Plans
CREATE TABLE subscription_plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_inr INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    contact_limit INTEGER NOT NULL
);

-- User Subscriptions
CREATE TABLE user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    plan_id TEXT REFERENCES subscription_plans(id),
    purchase_token TEXT UNIQUE NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Contact Usage Tracking
CREATE TABLE contact_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    listing_id UUID,
    used_at TIMESTAMP DEFAULT NOW()
);

