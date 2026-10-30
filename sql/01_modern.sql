-- Modern version: uses UUID, INET6 and CREATE OR REPLACE.
-- FOREIGN_KEY_CHECKS is switched off while replacing, because CREATE OR REPLACE on a table that
-- another table points to (links <- clicks) otherwise fails on a re-run (error 1451).
SET FOREIGN_KEY_CHECKS = 0;

CREATE OR REPLACE TABLE links (
  id UUID DEFAULT UUID() PRIMARY KEY,
  target_url VARCHAR(2048) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE TABLE clicks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  link_id UUID NOT NULL,
  client_ip INET6 NOT NULL,
  clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (link_id) REFERENCES links(id)
);

SET FOREIGN_KEY_CHECKS = 1;
