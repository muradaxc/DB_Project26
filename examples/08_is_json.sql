-- IS JSON: the SQL-standard test for "is this text valid JSON", usable inside a CHECK constraint,
-- so bad documents are rejected by the database instead of by application code.
-- NOTE: needs a MariaDB version that supports the IS JSON predicate. If you get a syntax error,
-- your version is too old; the older equivalent is CHECK (JSON_VALID(meta)).
CREATE OR REPLACE TABLE demo_json (
  id INT PRIMARY KEY,
  meta TEXT NOT NULL,
  CONSTRAINT meta_is_json CHECK (meta IS JSON)
);

INSERT INTO demo_json VALUES (1, '{"browser": "firefox", "mobile": false}');   -- accepted

-- Uncomment to see the rejection:
-- INSERT INTO demo_json VALUES (2, 'this is not json');                       -- ERROR: CHECK constraint failed

SELECT id, JSON_VALUE(meta, '$.browser') AS browser FROM demo_json;

DROP TABLE demo_json;
