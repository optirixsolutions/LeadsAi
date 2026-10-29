-- Runs once when the Postgres volume is first created.
-- `salesiq` (superuser, from POSTGRES_USER) owns the schema and runs migrations.
-- `salesiq_app` is the runtime role: not an owner, not a superuser, so row-level security applies.
-- Local development credentials only; production roles are provisioned by the platform.
CREATE ROLE salesiq_app LOGIN PASSWORD 'salesiq_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- Owns only the invitation_lookup() SECURITY DEFINER function. Cannot log in.
CREATE ROLE salesiq_definer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;

-- Disposable database for the automated test suite. Never point tests at a real database.
CREATE DATABASE salesiq_test OWNER salesiq;
