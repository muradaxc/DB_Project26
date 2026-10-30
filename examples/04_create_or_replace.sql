-- CREATE OR REPLACE: idempotent DDL, so scripts can be re-run safely.
-- WARNING: replacing a table throws away its data.
CREATE OR REPLACE TABLE demo_replace (id INT);
CREATE OR REPLACE TABLE demo_replace (id INT, extra VARCHAR(10));   -- rebuilt, no DROP needed
SHOW CREATE TABLE demo_replace;

-- The old way, every time:
--   DROP TABLE IF EXISTS demo_replace;
--   CREATE TABLE demo_replace (id INT, extra VARCHAR(10));

DROP TABLE demo_replace;
