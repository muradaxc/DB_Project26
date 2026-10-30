-- INTERSECT and EXCEPT: set operations that sit next to UNION.
CREATE OR REPLACE TABLE demo_clicks_a (ip VARCHAR(20));
CREATE OR REPLACE TABLE demo_clicks_b (ip VARCHAR(20));
INSERT INTO demo_clicks_a VALUES ('1.1.1.1'), ('2.2.2.2'), ('3.3.3.3');
INSERT INTO demo_clicks_b VALUES ('2.2.2.2'), ('3.3.3.3'), ('4.4.4.4');

-- IPs that clicked both links:
SELECT ip FROM demo_clicks_a INTERSECT SELECT ip FROM demo_clicks_b;
-- IPs that clicked link A but not link B:
SELECT ip FROM demo_clicks_a EXCEPT SELECT ip FROM demo_clicks_b;

-- The old way for the second question (and NOT IN breaks if the column contains NULL):
SELECT DISTINCT a.ip FROM demo_clicks_a a LEFT JOIN demo_clicks_b b ON a.ip = b.ip WHERE b.ip IS NULL;

DROP TABLE demo_clicks_a, demo_clicks_b;
