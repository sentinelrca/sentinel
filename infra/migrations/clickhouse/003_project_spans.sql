-- ClickHouse DDL for project_spans table
-- Stores immutable trace snapshots per offline analysis project.
-- Separate from the live `spans` table so project re-analysis is reproducible.
-- Applied automatically at worker startup via ensure_tables()
-- Run manually: clickhouse-client --query "$(cat 003_project_spans.sql)"

CREATE TABLE IF NOT EXISTS sentinel.project_spans (
    project_id      String,
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
ORDER BY (project_id, trace_id, span_id)
SETTINGS index_granularity = 8192;
