-- ============================================================
-- Singgah SmartAdvisor Database Migration
-- ============================================================

CREATE DATABASE IF NOT EXISTS singgah_chat
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE singgah_chat;

-- ============================================================
-- Tabel: sg_chat_session (data user/pengguna)
-- ============================================================
CREATE TABLE IF NOT EXISTS sg_chat_session (
    session          VARCHAR(36)   NOT NULL PRIMARY KEY,
    name             VARCHAR(25)   NOT NULL,
    phone            VARCHAR(15)   NOT NULL UNIQUE,
    status_pernikahan VARCHAR(15)  NOT NULL COMMENT 'lajang / menikah',
    budget_min       INT           NOT NULL COMMENT 'Budget minimum per bulan',
    budget_max       INT           NOT NULL COMMENT 'Budget maksimum per bulan',
    lokasi           VARCHAR(100)  NOT NULL COMMENT 'Lokasi yang dicari',

    INDEX idx_session (session),
    INDEX idx_name (name),
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================
-- Tabel: sg_chat_history (riwayat chat)
-- ============================================================
CREATE TABLE IF NOT EXISTS sg_chat_history (
    chat_id   INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session   VARCHAR(36)  NOT NULL,
    message   TEXT         NOT NULL,
    is_user   CHAR(1)      NOT NULL COMMENT 'Y = user, N = bot',
    `read`    CHAR(1)      NOT NULL DEFAULT 'N',
    replied   CHAR(1)      NOT NULL DEFAULT 'N',
    chattime  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_chat_id (chat_id),
    INDEX idx_session (session),
    INDEX idx_is_user (is_user),
    INDEX idx_chattime (chattime),

    CONSTRAINT fk_chat_session
        FOREIGN KEY (session) REFERENCES sg_chat_session(session)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
