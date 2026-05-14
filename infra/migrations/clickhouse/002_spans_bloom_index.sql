-- Online ALTER: no downtime, no data migration required.
-- Adds a Bloom filter skip index on span_id so the dedup SELECT in
-- insert_spans_dedup() can avoid full partition scans.
ALTER TABLE spans ADD INDEX IF NOT EXISTS idx_span_id span_id
    TYPE bloom_filter(0.01) GRANULARITY 4;
ALTER TABLE spans MATERIALIZE INDEX idx_span_id;
