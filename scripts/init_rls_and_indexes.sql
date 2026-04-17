-- =============================================================
-- EasyProcess: Row Level Security (RLS) & Performance Indexes
-- Run this AFTER the application has created the tables.
-- =============================================================

-- -----------------------------------------------
-- 1. Enable RLS on all tables
-- -----------------------------------------------
ALTER TABLE easyprocess.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE easyprocess.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE easyprocess.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE easyprocess.social_accounts ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------
-- 2. RLS Policies
--    Backend connects as `postgres` (service role) = full access.
--    anon/authenticated via Supabase client = blocked.
-- -----------------------------------------------

-- Service role: full access on all tables
CREATE POLICY "service_role_full_users" ON easyprocess.users
    FOR ALL TO postgres USING (true) WITH CHECK (true);
CREATE POLICY "service_role_full_sessions" ON easyprocess.sessions
    FOR ALL TO postgres USING (true) WITH CHECK (true);
CREATE POLICY "service_role_full_audit_logs" ON easyprocess.audit_logs
    FOR ALL TO postgres USING (true) WITH CHECK (true);
CREATE POLICY "service_role_full_social_accounts" ON easyprocess.social_accounts
    FOR ALL TO postgres USING (true) WITH CHECK (true);

-- Deny anon/authenticated on all tables
CREATE POLICY "anon_deny_users" ON easyprocess.users
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "authenticated_deny_users" ON easyprocess.users
    FOR ALL TO authenticated USING (false) WITH CHECK (false);

CREATE POLICY "anon_deny_sessions" ON easyprocess.sessions
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "authenticated_deny_sessions" ON easyprocess.sessions
    FOR ALL TO authenticated USING (false) WITH CHECK (false);

CREATE POLICY "anon_deny_audit_logs" ON easyprocess.audit_logs
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "authenticated_deny_audit_logs" ON easyprocess.audit_logs
    FOR ALL TO authenticated USING (false) WITH CHECK (false);

CREATE POLICY "anon_deny_social_accounts" ON easyprocess.social_accounts
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "authenticated_deny_social_accounts" ON easyprocess.social_accounts
    FOR ALL TO authenticated USING (false) WITH CHECK (false);

-- -----------------------------------------------
-- 3. Performance indexes
--    (beyond what SQLAlchemy creates from model definitions)
-- -----------------------------------------------

-- Users: lookup by active status
CREATE INDEX IF NOT EXISTS idx_users_is_active
    ON easyprocess.users (is_active);

-- Users: locked accounts
CREATE INDEX IF NOT EXISTS idx_users_locked_until
    ON easyprocess.users (locked_until)
    WHERE locked_until IS NOT NULL;

-- Sessions: cleanup expired/revoked
CREATE INDEX IF NOT EXISTS idx_sessions_cleanup
    ON easyprocess.sessions (expires_at, revoked_at);

-- Audit logs: recent events per user
CREATE INDEX IF NOT EXISTS idx_audit_user_created
    ON easyprocess.audit_logs (user_id, created_at DESC);

-- Social accounts: lookup by provider + provider_user_id
-- (already has a unique index from model definition)
