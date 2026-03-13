CREATE DATABASE IF NOT EXISTS tcrt_main
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS tcrt_audit
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS tcrt_usm
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'tcrt'@'%' IDENTIFIED BY 'tcrt';

GRANT ALL PRIVILEGES ON tcrt_main.* TO 'tcrt'@'%';
GRANT ALL PRIVILEGES ON tcrt_audit.* TO 'tcrt'@'%';
GRANT ALL PRIVILEGES ON tcrt_usm.* TO 'tcrt'@'%';

FLUSH PRIVILEGES;
