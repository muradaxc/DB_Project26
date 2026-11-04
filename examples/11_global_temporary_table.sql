-- Global temporary table: the table is defined once, like a normal table, but every session only
-- ever sees its own rows, and they disappear when the session ends (or at COMMIT, with
-- ON COMMIT DELETE ROWS). The hackathon page lists this for MariaDB 12.3; check your version.
-- The old way: every session runs CREATE TEMPORARY TABLE itself before it can use one.
CREATE GLOBAL TEMPORARY TABLE demo_click_batch (ip INET6 NOT NULL) ON COMMIT PRESERVE ROWS;

INSERT INTO demo_click_batch VALUES ('::ffff:10.0.0.2'), ('::ffff:10.0.0.10');
SELECT * FROM demo_click_batch;                      -- this session's rows only
-- Open a second client and run SELECT * FROM demo_click_batch: it is empty there.

TRUNCATE TABLE demo_click_batch;                     -- a GTT cannot be dropped while it holds rows
DROP TABLE demo_click_batch;
