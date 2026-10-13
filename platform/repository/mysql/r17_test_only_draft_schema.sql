-- R17: dedicated TEST_ONLY schema only. Never run in STORY_OS_RUNTIME.
CREATE TABLE IF NOT EXISTS r17_draft_bundles (
 bundle_id VARCHAR(64) PRIMARY KEY,
 source_sha CHAR(64) NOT NULL UNIQUE,
 backup_json JSON NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS r17_draft_projects (
 project_id VARCHAR(64) PRIMARY KEY,
 bundle_id VARCHAR(64) NOT NULL,
 source_id VARCHAR(100) NOT NULL UNIQUE,
 title VARCHAR(220) NOT NULL,
 CONSTRAINT fk_r17_project_bundle FOREIGN KEY (bundle_id) REFERENCES r17_draft_bundles(bundle_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS r17_draft_episodes (
 draft_id VARCHAR(64) PRIMARY KEY,
 bundle_id VARCHAR(64) NOT NULL,
 source_id VARCHAR(100) NOT NULL UNIQUE,
 title VARCHAR(220) NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 CONSTRAINT fk_r17_episode_bundle FOREIGN KEY (bundle_id) REFERENCES r17_draft_bundles(bundle_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS r17_draft_requests (
 request_id VARCHAR(100) PRIMARY KEY,
 payload_sha CHAR(64) NOT NULL,
 result_json JSON NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS r17_draft_audit (
 audit_id CHAR(36) PRIMARY KEY,
 action VARCHAR(60) NOT NULL,
 subject_id VARCHAR(64) NOT NULL,
 request_id VARCHAR(100) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;

-- User-created Project and Episode snapshot - browser drafts only, never canonical runtime.
CREATE TABLE IF NOT EXISTS r17_saved_workspaces (
  workspace_id VARCHAR(64) PRIMARY KEY,
  version INT NOT NULL,
  backup_json JSON NOT NULL,
  created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB;
