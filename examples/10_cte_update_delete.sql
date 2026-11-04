-- UPDATE and DELETE that read from a CTE (WITH ...). Needs MariaDB 12.3 or newer.
-- The CTE names the rows to change once, readably, and is used by the statement itself.
-- The old way: fetch the ids into the application and send one statement per row, or nest the
-- same query as a derived table inside the UPDATE/DELETE.
CREATE OR REPLACE TABLE demo_cte_links (id INT PRIMARY KEY, click_count INT NOT NULL DEFAULT 0);
CREATE OR REPLACE TABLE demo_cte_clicks (id INT AUTO_INCREMENT PRIMARY KEY, link_id INT NOT NULL);
INSERT INTO demo_cte_links (id) VALUES (1), (2), (3), (4);
INSERT INTO demo_cte_clicks (link_id) VALUES (1), (1), (3);

-- Refresh the stored click counters.
WITH counts AS (SELECT link_id, COUNT(*) AS n FROM demo_cte_clicks GROUP BY link_id)
UPDATE demo_cte_links SET click_count = (SELECT n FROM counts WHERE counts.link_id = demo_cte_links.id)
WHERE id IN (SELECT link_id FROM counts);

SELECT * FROM demo_cte_links;                       -- 1 -> 2 clicks, 3 -> 1 click

-- Delete links nobody ever clicked.
WITH stale AS (
  SELECT l.id FROM demo_cte_links l LEFT JOIN demo_cte_clicks c ON c.link_id = l.id WHERE c.link_id IS NULL
)
DELETE FROM demo_cte_links WHERE id IN (SELECT id FROM stale);

SELECT * FROM demo_cte_links;                       -- only links 1 and 3 are left

DROP TABLE demo_cte_links, demo_cte_clicks;
