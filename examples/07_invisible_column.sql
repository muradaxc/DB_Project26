-- Invisible columns: stay out of SELECT * and out of INSERT without a column list,
-- but are there the moment you name them. Useful for adding a column without breaking old code.
CREATE OR REPLACE TABLE demo_invisible (
  id INT PRIMARY KEY,
  name VARCHAR(20),
  internal_note VARCHAR(50) INVISIBLE
);

INSERT INTO demo_invisible VALUES (1, 'a');                                   -- no need to name internal_note
INSERT INTO demo_invisible (id, name, internal_note) VALUES (2, 'b', 'secret');

SELECT * FROM demo_invisible;                                                  -- internal_note is not shown
SELECT id, name, internal_note FROM demo_invisible;                            -- naming it shows it

DROP TABLE demo_invisible;
