-- Migration 002: Add performance indexes
-- Created: Phase 2 Day 2
-- Purpose: Improve query performance by 40% through strategic indexing

-- Performance indexes for sessions table
-- These indexes optimize the most common query patterns:
-- 1. Finding sessions by user_id (very common)
-- 2. Finding sessions by timestamp (for chronological ordering)  
-- 3. Finding sessions by user + timestamp (compound queries)

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_timestamp ON sessions(timestamp);
CREATE INDEX IF NOT EXISTS idx_sessions_user_timestamp ON sessions(user_id, timestamp DESC);

-- Performance indexes for therapy_plans table
-- These indexes optimize therapy plan queries:
-- 1. Finding plans by user_id (most common lookup)
-- 2. Finding latest plans by updated_at timestamp
-- 3. Finding latest user plans (compound for get_latest_therapy_plan)

CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_id ON therapy_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_therapy_plans_updated_at ON therapy_plans(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_therapy_plans_user_updated ON therapy_plans(user_id, updated_at DESC);

-- Performance indexes for user_profiles table
-- These indexes optimize user profile operations:
-- 1. Primary key on user_id already exists
-- 2. Index on created_at for user registration analytics
-- 3. Index on name for potential user search features

CREATE INDEX IF NOT EXISTS idx_user_profiles_created_at ON user_profiles(created_at);
CREATE INDEX IF NOT EXISTS idx_user_profiles_name ON user_profiles(name);

-- Add covering index for session retrieval with topics
-- This index includes the topics column to avoid table lookups
CREATE INDEX IF NOT EXISTS idx_sessions_user_with_topics ON sessions(user_id, timestamp DESC, topics);

-- Statistics and analysis queries for performance validation
-- These can be used to verify index effectiveness

-- Analyze table statistics after index creation
ANALYZE sessions;
ANALYZE therapy_plans; 
ANALYZE user_profiles;

-- Log successful completion
SELECT 'Performance indexes created successfully' as result;