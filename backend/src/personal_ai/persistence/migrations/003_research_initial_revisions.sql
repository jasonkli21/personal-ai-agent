-- Existing research contracts define an unclaimed aggregate at revision zero.
-- The first conditional claim advances it to revision one.
ALTER TABLE research_sessions
    DROP CONSTRAINT IF EXISTS research_sessions_revision_check;
ALTER TABLE research_sessions
    ADD CONSTRAINT research_sessions_revision_nonnegative CHECK (revision >= 0);

ALTER TABLE iterative_research_runs
    DROP CONSTRAINT IF EXISTS iterative_research_runs_revision_check;
ALTER TABLE iterative_research_runs
    ADD CONSTRAINT iterative_research_runs_revision_nonnegative CHECK (revision >= 0);
