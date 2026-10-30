-- RETURNING: statements hand back the rows they touched, so no second SELECT is needed.
-- The old way needs a follow-up SELECT (and LAST_INSERT_ID() only works for AUTO_INCREMENT).
CREATE OR REPLACE TABLE demo_returning (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(30),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO demo_returning (name) VALUES ('a'), ('b') RETURNING id, created_at;
DELETE FROM demo_returning WHERE id = 2 RETURNING *;

-- The hackathon page also lists UPDATE ... RETURNING. It is a syntax error on MariaDB 10.11
-- (we tested), so check it on YOUR version before relying on it:
-- UPDATE demo_returning SET name = UPPER(name) WHERE id = 1 RETURNING id, name;

DROP TABLE demo_returning;
