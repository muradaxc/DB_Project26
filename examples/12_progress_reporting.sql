-- Progress reporting: long statements such as ALTER TABLE ... ALGORITHM=COPY report how far they
-- are, so a second connection can watch them instead of guessing.
-- Run the ALTER in one client and the SELECT in a second client while it runs.
-- (python/migration.py does exactly that automatically and records the readings.)
CREATE OR REPLACE TABLE demo_progress (id INT PRIMARY KEY, payload VARCHAR(50));
INSERT INTO demo_progress SELECT seq, CONCAT('row-', seq) FROM seq_1_to_1000000;

-- Client 1:
ALTER TABLE demo_progress FORCE, ALGORITHM=COPY;

-- Client 2, while client 1 is busy:
--   SELECT ID, STAGE, MAX_STAGE, PROGRESS, INFO FROM information_schema.PROCESSLIST
--   WHERE INFO LIKE 'ALTER TABLE demo_progress%';
-- The command-line client also prints progress by itself for long statements.

DROP TABLE demo_progress;
