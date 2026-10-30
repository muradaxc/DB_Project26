-- INET6 / INET4: IP addresses as numbers instead of text, so they sort correctly.
CREATE OR REPLACE TABLE demo_ip6 (ip INET6 NOT NULL);
-- IPv4 must be written in IPv4-mapped form for INET6:
INSERT INTO demo_ip6 VALUES ('::ffff:10.0.0.2'), ('::ffff:10.0.0.10'), ('::ffff:10.0.0.9'), ('2001:db8::1');
SELECT ip FROM demo_ip6 ORDER BY ip;           -- numeric order: .2, .9, .10

-- A plain IPv4 string is rejected by INET6 (uncomment to see the error):
-- INSERT INTO demo_ip6 VALUES ('10.0.0.2');

-- INET4 is IPv4-only (4 bytes) and accepts plain IPv4 text:
CREATE OR REPLACE TABLE demo_ip4 (ip INET4 NOT NULL);
INSERT INTO demo_ip4 VALUES ('10.0.0.2'), ('10.0.0.10'), ('10.0.0.9');
SELECT ip FROM demo_ip4 ORDER BY ip;

-- The old way: VARCHAR(45) sorts as text, so '10.0.0.10' comes before '10.0.0.2'.
CREATE OR REPLACE TABLE demo_ip_text (ip VARCHAR(45) NOT NULL);
INSERT INTO demo_ip_text VALUES ('10.0.0.2'), ('10.0.0.10'), ('10.0.0.9');
SELECT ip FROM demo_ip_text ORDER BY ip;

DROP TABLE demo_ip6, demo_ip4, demo_ip_text;
