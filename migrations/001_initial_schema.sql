-- Migration 001: Initial schema (baseline for existing tables)
-- This represents the current state of the database
-- Created: Phase 2 Day 2

-- This migration is a baseline migration that documents the existing schema
-- The actual tables are already created by the DatabaseService._initialize_database() method

-- Sessions table
-- CREATE TABLE IF NOT EXISTS sessions (
--     session_id TEXT PRIMARY KEY,
--     user_id TEXT NOT NULL,
--     timestamp TEXT NOT NULL,
--     transcript TEXT NOT NULL,
--     topics TEXT  -- Added in later ALTER TABLE
-- );

-- Therapy plans table  
-- CREATE TABLE IF NOT EXISTS therapy_plans (
--     plan_id TEXT PRIMARY KEY,
--     user_id TEXT NOT NULL,
--     created_at TEXT NOT NULL,
--     updated_at TEXT NOT NULL,
--     plan_details TEXT NOT NULL,
--     version INTEGER NOT NULL,
--     selected_therapy_style TEXT  -- Added in later ALTER TABLE
-- );

-- User profiles table
-- CREATE TABLE IF NOT EXISTS user_profiles (
--     user_id TEXT PRIMARY KEY,
--     name TEXT NOT NULL,
--     birthdate TEXT,
--     profession TEXT,
--     created_at TEXT NOT NULL,
--     updated_at TEXT NOT NULL
-- );

-- This migration serves as documentation for the baseline schema
-- Actual table creation is handled by DatabaseService._initialize_database()
SELECT 'Baseline schema documented' as result;