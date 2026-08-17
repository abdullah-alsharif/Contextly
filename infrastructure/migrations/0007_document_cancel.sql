-- 'cancelled': terminal status for a queued/processing row the owner cancelled
-- (POST /documents/{id}/cancel); the worker polls the row and aborts
-- (docs/ingestion.md §1).

alter type document_status add value 'cancelled';
