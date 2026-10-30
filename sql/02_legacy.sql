-- Legacy version: the same job without the new features (the "before")
DROP TABLE IF EXISTS clicks_legacy;
DROP TABLE IF EXISTS links_legacy;

CREATE TABLE links_legacy (
  id CHAR(36) PRIMARY KEY,
  target_url VARCHAR(2048) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE clicks_legacy (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  link_id CHAR(36) NOT NULL,
  client_ip VARCHAR(45) NOT NULL,
  clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (link_id) REFERENCES links_legacy(id)
);
