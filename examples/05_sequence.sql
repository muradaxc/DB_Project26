-- CREATE SEQUENCE: a counter that is its own object, not tied to one table's AUTO_INCREMENT.
-- Handy for short codes, invoice numbers, or ids shared by several tables.
CREATE OR REPLACE SEQUENCE demo_code_seq START WITH 1000 INCREMENT BY 1;

SELECT NEXTVAL(demo_code_seq) AS first_code, NEXTVAL(demo_code_seq) AS second_code;

CREATE OR REPLACE TABLE demo_seq_links (
  code BIGINT DEFAULT NEXTVAL(demo_code_seq) PRIMARY KEY,
  target_url VARCHAR(200)
);
INSERT INTO demo_seq_links (target_url) VALUES ('https://example.com/a'), ('https://example.com/b')
RETURNING code, target_url;

DROP TABLE demo_seq_links;
DROP SEQUENCE demo_code_seq;
