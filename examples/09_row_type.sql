-- ROW type in stored procedures: one variable that holds a whole row.
-- ROW TYPE OF <table> follows the table's columns automatically, so adding a column to the table
-- does not mean editing every procedure that copies its rows.
-- The old way needs one DECLARE and one INTO target per column.
CREATE OR REPLACE TABLE demo_row_links (
  id INT PRIMARY KEY,
  target_url VARCHAR(200) NOT NULL,
  clicks INT NOT NULL DEFAULT 0
);
INSERT INTO demo_row_links VALUES (1, 'https://example.com/a', 0), (2, 'https://example.com/b', 5);

DELIMITER //
CREATE OR REPLACE PROCEDURE demo_row_visit(IN p_id INT)
BEGIN
  DECLARE link ROW TYPE OF demo_row_links;          -- modern: 1 declaration for the whole row
  SELECT * INTO link FROM demo_row_links WHERE id = p_id;
  UPDATE demo_row_links SET clicks = link.clicks + 1 WHERE id = link.id;
  SELECT link.id, link.target_url, link.clicks + 1 AS clicks_now;
END//

CREATE OR REPLACE PROCEDURE demo_row_visit_legacy(IN p_id INT)
BEGIN
  DECLARE v_id INT;                                  -- legacy: one variable per column
  DECLARE v_url VARCHAR(200);
  DECLARE v_clicks INT;
  SELECT id, target_url, clicks INTO v_id, v_url, v_clicks FROM demo_row_links WHERE id = p_id;
  UPDATE demo_row_links SET clicks = v_clicks + 1 WHERE id = v_id;
  SELECT v_id, v_url, v_clicks + 1 AS clicks_now;
END//
DELIMITER ;

CALL demo_row_visit(2);
CALL demo_row_visit_legacy(2);

DROP PROCEDURE demo_row_visit;
DROP PROCEDURE demo_row_visit_legacy;
DROP TABLE demo_row_links;
