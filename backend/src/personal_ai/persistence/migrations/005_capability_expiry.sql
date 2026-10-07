-- Maintenance purges are bounded, owner-wide reads in the selected app/workspace.
CREATE INDEX IF NOT EXISTS booking_extractions_app_expiry_idx
    ON booking_document_extractions(application_id, workspace_id, status, expires_at, record_id)
    WHERE status = 'completed';
