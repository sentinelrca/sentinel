-- ClickHouse DDL for SentinelAI spans table
-- Applied automatically at worker startup via ensure_tables()
-- Run manually: clickhouse-client --query "$(cat 001_spans.sql)"

CREATE TABLE IF NOT EXISTS spans (
    trace_id        String,
    span_id         String,
    parent_span_id  String DEFAULT '',
    workspace_id    String,
    name            String,
    kind            String,
    status          String,
    start_time      DateTime64(3, 'UTC'),
    end_time        DateTime64(3, 'UTC'),
    model           String DEFAULT '',
    agent_name      String DEFAULT '',
    input_tokens    Int64  DEFAULT 0,
    output_tokens   Int64  DEFAULT 0,
    retry_count     Int32  DEFAULT 0,
    error_message   String DEFAULT '',
    attributes_json String DEFAULT '{}'
) ENGINE = MergeTree()
ORDER BY (workspace_id, toDate(start_time), trace_id)
SETTINGS index_granularity = 8192;
