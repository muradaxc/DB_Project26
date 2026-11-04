-- Tables for the web app (python/app.py): the link shortener people actually use.
-- Every feature here is one the comparison measures:
--   SEQUENCE          short codes (no AUTO_INCREMENT tied to one table, no app-side counter)
--   UUID              internal id, made by the server
--   INET6             visitor IPs, IPv4 and IPv6 in one column, sorted as addresses
--   IS JSON           click details are checked by the database, not only by the app
--   INVISIBLE         a column old "SELECT *" code never sees
--   CREATE OR REPLACE the script can be re-run (FOREIGN_KEY_CHECKS off while replacing, see README)
-- Needs MariaDB 13.0.2 (the version this project pins) or another version with IS JSON.
SET FOREIGN_KEY_CHECKS = 0;

CREATE OR REPLACE SEQUENCE app_code_seq START WITH 100000 INCREMENT BY 1;

CREATE OR REPLACE TABLE app_links (
  id UUID DEFAULT UUID() PRIMARY KEY,
  code BIGINT NOT NULL DEFAULT NEXTVAL(app_code_seq) UNIQUE,
  target_url VARCHAR(2048) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  created_from INET6 NULL INVISIBLE
);

CREATE OR REPLACE TABLE app_clicks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  link_id UUID NOT NULL,
  client_ip INET6 NOT NULL,
  meta TEXT NOT NULL,
  clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT click_meta_is_json CHECK (meta IS JSON),
  KEY (link_id, clicked_at),
  FOREIGN KEY (link_id) REFERENCES app_links(id)
);

SET FOREIGN_KEY_CHECKS = 1;
