SET NAMES utf8mb4;
CREATE DATABASE board_club;
USE board_club;

CREATE TABLE genre (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE game (
    id INT AUTO_INCREMENT PRIMARY KEY,
    genre_id INT NOT NULL,
    title VARCHAR(100) NOT NULL UNIQUE,
    min_players TINYINT NOT NULL,
    max_players TINYINT NOT NULL,
    duration_min SMALLINT NOT NULL,
    complexity TINYINT NOT NULL,
    copies TINYINT NOT NULL DEFAULT 1,
    CONSTRAINT fk_game_genre FOREIGN KEY (genre_id) REFERENCES genre(id) ON DELETE RESTRICT,
    CONSTRAINT chk_game_min CHECK (min_players >= 1),
    CONSTRAINT chk_game_players CHECK (max_players >= min_players),
    CONSTRAINT chk_game_copies CHECK (copies >= 1),
    CONSTRAINT chk_game_complex CHECK (complexity BETWEEN 1 AND 5),
    CONSTRAINT chk_game_duration CHECK (duration_min > 0)
);

CREATE TABLE player (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    nickname VARCHAR(30) NOT NULL UNIQUE,
    registered_at DATE NOT NULL DEFAULT (CURRENT_DATE),
    rating INT NOT NULL DEFAULT 1000,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    banned_until DATETIME NULL,
    ban_reason VARCHAR(512) NULL,
    INDEX idx_player_name (name),
    INDEX idx_player_banned (banned_until)
);

CREATE TABLE game_table (
    id INT AUTO_INCREMENT PRIMARY KEY,
    number INT NULL UNIQUE,
    capacity TINYINT NOT NULL,
    description VARCHAR(255) NULL,
    CONSTRAINT chk_table_capacity CHECK (capacity >= 2)
);

CREATE TABLE staff (
    id INT AUTO_INCREMENT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    login VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'host') NOT NULL
);

CREATE TABLE session (
    id INT AUTO_INCREMENT PRIMARY KEY,
    game_id INT NOT NULL,
    table_id INT NOT NULL,
    host_id INT NOT NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NOT NULL,
    status ENUM('planned', 'active', 'finished', 'cancelled') NOT NULL DEFAULT 'planned',
    CONSTRAINT fk_session_game FOREIGN KEY (game_id) REFERENCES game(id) ON DELETE RESTRICT,
    CONSTRAINT fk_session_table FOREIGN KEY (table_id) REFERENCES game_table(id) ON DELETE RESTRICT,
    CONSTRAINT fk_session_host FOREIGN KEY (host_id)  REFERENCES staff(id) ON DELETE RESTRICT,
    CONSTRAINT chk_session_time CHECK (ends_at > starts_at),
    INDEX idx_session_starts (starts_at)
);

CREATE TABLE session_player (
    session_id INT NOT NULL,
    player_id INT NOT NULL,
    score INT NULL,
    place TINYINT NULL,
    rating_delta INT NULL,
    attended BOOLEAN NULL,
    PRIMARY KEY (session_id, player_id),
    CONSTRAINT fk_sp_session FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE,
    CONSTRAINT fk_sp_player FOREIGN KEY (player_id)  REFERENCES player(id) ON DELETE RESTRICT,
    CONSTRAINT chk_sp_place CHECK (place IS NULL OR place >= 1),
    CONSTRAINT chk_sp_score CHECK (score IS NULL OR score >= 0)
);

-- ============================================================
--  ТРИГГЕРЫ
-- ============================================================
DELIMITER //

-- Проверки при добавлении игрока в партию
CREATE TRIGGER trg_sp_before_insert BEFORE INSERT ON session_player
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_max, v_cap, v_cnt INT;
    DECLARE v_active BOOLEAN;
    DECLARE v_banned_until DATETIME;
    DECLARE v_target_start, v_target_end DATETIME;
    DECLARE v_msg VARCHAR(255);

    SELECT s.status, g.max_players, t.capacity, s.starts_at, s.ends_at
      INTO v_status, v_max, v_cap, v_target_start, v_target_end
      FROM session s
      JOIN game g ON g.id = s.game_id
      JOIN game_table t ON t.id = s.table_id
     WHERE s.id = NEW.session_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Партия не найдена';
    END IF;
    IF v_status <> 'planned' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Состав можно менять только у запланированной партии';
    END IF;

    SELECT is_active, banned_until INTO v_active, v_banned_until
      FROM player WHERE id = NEW.player_id;

    IF v_active = FALSE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Игрок деактивирован и не может участвовать в партиях';
    END IF;
    IF v_banned_until IS NOT NULL AND v_banned_until > NOW() THEN
        SET v_msg = CONCAT('Игрок забанен до ', DATE_FORMAT(v_banned_until, '%d.%m.%Y %H:%i'));
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    -- Игрок не должен быть в другой партии в пересекающееся время
    IF EXISTS (
        SELECT 1
          FROM session_player sp
          JOIN session s2 ON s2.id = sp.session_id
         WHERE sp.player_id = NEW.player_id
           AND s2.status IN ('planned','active')
           AND s2.id <> NEW.session_id
           AND s2.starts_at < v_target_end
           AND s2.ends_at > v_target_start
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Игрок уже участвует в другой партии в это время';
    END IF;

    SELECT COUNT(*) INTO v_cnt FROM session_player WHERE session_id = NEW.session_id;
    IF v_cnt >= v_max THEN
        SET v_msg = CONCAT('Максимум игроков для этой игры: ', v_max);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    IF v_cnt >= v_cap THEN
        SET v_msg = CONCAT('Мест за этим столом: ', v_cap);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
END//

-- Обновления в session_player: строгая блокировка результатов + attended
CREATE TRIGGER trg_sp_before_update BEFORE UPDATE ON session_player
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    SELECT status INTO v_status FROM session WHERE id = NEW.session_id;

    IF NOT (NEW.score <=> OLD.score)
       OR NOT (NEW.place <=> OLD.place)
       OR NOT (NEW.rating_delta <=> OLD.rating_delta) THEN
        IF v_status <> 'active' THEN
            IF v_status = 'finished' THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Результаты завершённой партии изменять нельзя';
            ELSE
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Очки можно вводить только во время партии';
            END IF;
        END IF;
    END IF;

    IF NOT (NEW.attended <=> OLD.attended) AND v_status NOT IN ('active','finished') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Отметить посещаемость можно только у идущей или завершённой партии';
    END IF;
END//

-- Удаление участника — только у запланированной партии
CREATE TRIGGER trg_sp_before_delete BEFORE DELETE ON session_player
FOR EACH ROW
BEGIN
    DECLARE v_status VARCHAR(20);
    SELECT status INTO v_status FROM session WHERE id = OLD.session_id;
    IF v_status <> 'planned' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Состав можно менять только у запланированной партии';
    END IF;
END//

-- Обновление партии: запрет изменять завершённые/отменённые + защита от конфликтов при переносе
CREATE TRIGGER trg_session_before_update BEFORE UPDATE ON session
FOR EACH ROW
BEGIN
    DECLARE v_copies INT;

    IF OLD.status IN ('finished', 'cancelled') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Завершённую или отменённую партию изменять нельзя';
    END IF;

    IF NEW.status IN ('planned','active')
       AND (NEW.starts_at <> OLD.starts_at
            OR NEW.ends_at <> OLD.ends_at
            OR NEW.table_id <> OLD.table_id) THEN

        -- Стол занят в новое время?
        IF EXISTS (
            SELECT 1 FROM session
             WHERE table_id = NEW.table_id
               AND id <> NEW.id
               AND status IN ('planned','active')
               AND starts_at < NEW.ends_at
               AND ends_at > NEW.starts_at
        ) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Стол занят в это время, выберите другой';
        END IF;

        -- Копии игры не должны быть исчерпаны
        SELECT copies INTO v_copies FROM game WHERE id = NEW.game_id;
        IF (SELECT COUNT(*) FROM session
             WHERE game_id = NEW.game_id
               AND id <> NEW.id
               AND status IN ('planned','active')
               AND starts_at < NEW.ends_at
               AND ends_at > NEW.starts_at) >= v_copies THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Свободных копий игры на это время нет';
        END IF;

        -- Участники партии не должны быть заняты в других партиях
        IF EXISTS (
            SELECT 1
              FROM session_player sp_target
              JOIN session_player sp_other ON sp_other.player_id = sp_target.player_id
              JOIN session s_other ON s_other.id = sp_other.session_id
             WHERE sp_target.session_id = NEW.id
               AND s_other.id <> NEW.id
               AND s_other.status IN ('planned','active')
               AND s_other.starts_at < NEW.ends_at
               AND s_other.ends_at > NEW.starts_at
        ) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Некоторые участники заняты в это время';
        END IF;
    END IF;
END//

-- Нельзя удалить игру, по которой есть незавершённые партии
CREATE TRIGGER trg_game_before_delete BEFORE DELETE ON game
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM session
                WHERE game_id = OLD.id AND status IN ('planned', 'active')) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Нельзя удалить игру: по ней есть незавершённые партии';
    END IF;
END//

-- ============================================================
--  ХРАНИМЫЕ ПРОЦЕДУРЫ
-- ============================================================

CREATE PROCEDURE sp_create_session(
    IN p_game_id INT, IN p_table_id INT, IN p_host_id INT,
    IN p_starts DATETIME, IN p_ends DATETIME, IN p_players JSON)
BEGIN
    DECLARE v_copies, v_min, v_max, v_busy, v_cnt, v_table, v_id INT;
    DECLARE v_msg VARCHAR(255);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_ends <= p_starts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Время окончания должно быть позже времени начала';
    END IF;

    START TRANSACTION;
    SELECT copies, min_players, max_players INTO v_copies, v_min, v_max
      FROM game WHERE id = p_game_id FOR UPDATE;
    IF v_copies IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Игра не найдена';
    END IF;

    SELECT id INTO v_table FROM game_table WHERE id = p_table_id FOR UPDATE;
    IF v_table IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Стол не найден';
    END IF;

    IF EXISTS (SELECT 1 FROM session
                WHERE table_id = p_table_id AND status IN ('planned', 'active')
                  AND starts_at < p_ends AND ends_at > p_starts) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Стол занят в это время, выберите другой';
    END IF;

    SELECT COUNT(*) INTO v_busy FROM session
     WHERE game_id = p_game_id AND status IN ('planned', 'active')
       AND starts_at < p_ends AND ends_at > p_starts;
    IF v_busy >= v_copies THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Свободных копий игры на это время нет';
    END IF;

    SET v_cnt = COALESCE(JSON_LENGTH(p_players), 0);
    IF v_cnt < v_min OR v_cnt > v_max THEN
        SET v_msg = CONCAT('Для этой игры нужно от ', v_min, ' до ', v_max, ' игроков');
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    INSERT INTO session (game_id, table_id, host_id, starts_at, ends_at)
    VALUES (p_game_id, p_table_id, p_host_id, p_starts, p_ends);
    SET v_id = LAST_INSERT_ID();

    INSERT INTO session_player (session_id, player_id)
    SELECT v_id, j.player_id
      FROM JSON_TABLE(p_players, '$[*]' COLUMNS (player_id INT PATH '$')) AS j;

    COMMIT;
    SELECT v_id AS id;
END//

CREATE PROCEDURE sp_start_session(IN p_session_id INT)
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_min, v_cnt INT;
    DECLARE v_msg VARCHAR(255);

    SELECT s.status, g.min_players INTO v_status, v_min
      FROM session s JOIN game g ON g.id = s.game_id
     WHERE s.id = p_session_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Партия не найдена';
    END IF;
    IF v_status <> 'planned' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Начать можно только запланированную партию';
    END IF;

    SELECT COUNT(*) INTO v_cnt FROM session_player WHERE session_id = p_session_id;
    IF v_cnt < v_min THEN
        SET v_msg = CONCAT('Минимум игроков для этой игры: ', v_min);
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;

    UPDATE session SET status = 'active' WHERE id = p_session_id;
END//

CREATE PROCEDURE sp_finish_session(IN p_session_id INT)
BEGIN
    DECLARE v_status VARCHAR(20);
    DECLARE v_n INT;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT status INTO v_status FROM session WHERE id = p_session_id FOR UPDATE;
    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Партия не найдена';
    END IF;
    IF v_status <> 'active' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Завершить можно только идущую партию';
    END IF;
    IF EXISTS (SELECT 1 FROM session_player WHERE session_id = p_session_id AND score IS NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Очки введены не у всех участников';
    END IF;

    SELECT COUNT(*) INTO v_n FROM session_player WHERE session_id = p_session_id;

    -- ROW_NUMBER гарантирует уникальные места (сумма ΔR = 0 по BR-08)
    UPDATE session_player sp
      JOIN (SELECT player_id,
                   CAST(ROW_NUMBER() OVER (ORDER BY score DESC, player_id ASC) AS SIGNED) AS rk
              FROM session_player WHERE session_id = p_session_id) r
        ON r.player_id = sp.player_id
       SET sp.place = r.rk,
           sp.rating_delta = 5 * (v_n - 2 * r.rk + 1)
     WHERE sp.session_id = p_session_id;

    UPDATE player p
      JOIN session_player sp ON sp.player_id = p.id
       SET p.rating = p.rating + sp.rating_delta
     WHERE sp.session_id = p_session_id;

    UPDATE session SET status = 'finished' WHERE id = p_session_id;

    COMMIT;
END//

DELIMITER ;

-- ============================================================
--  ПРЕДСТАВЛЕНИЯ
-- ============================================================
CREATE VIEW v_player_rating AS
SELECT RANK() OVER (ORDER BY p.rating DESC)           AS place,
       p.nickname,
       p.rating,
       COUNT(fs.session_id)                          AS games_played,
       COALESCE(SUM(fs.place = 1), 0)                AS wins,
       COALESCE(ROUND(100 * SUM(fs.place = 1) / NULLIF(COUNT(fs.session_id), 0)), 0) AS win_pct
  FROM player p
  LEFT JOIN (SELECT sp.player_id, sp.session_id, sp.place
               FROM session_player sp
               JOIN session s ON s.id = sp.session_id
              WHERE s.status = 'finished') fs
         ON fs.player_id = p.id
 WHERE p.is_active
 GROUP BY p.id, p.nickname, p.rating;

CREATE VIEW v_player_history AS
SELECT p.nickname,
       s.starts_at,
       g.title AS game,
       (SELECT COUNT(*) FROM session_player x WHERE x.session_id = s.id) AS players,
       sp.score,
       sp.place,
       sp.rating_delta
  FROM session_player sp
  JOIN player p  ON p.id = sp.player_id
  JOIN session s ON s.id = sp.session_id
  JOIN game g    ON g.id = s.game_id
 WHERE s.status = 'finished' AND p.is_active;

-- ============================================================
--  ПРАВА
-- ============================================================
DROP USER IF EXISTS 'club_admin'@'%', 'club_host'@'%', 'club_viewer'@'%';
CREATE USER IF NOT EXISTS 'club_admin'@'%'  IDENTIFIED BY 'admin_pass';
CREATE USER IF NOT EXISTS 'club_host'@'%'   IDENTIFIED BY 'host_pass';
CREATE USER IF NOT EXISTS 'club_viewer'@'%' IDENTIFIED BY 'viewer_pass';

GRANT ALL PRIVILEGES ON board_club.* TO 'club_admin'@'%';

GRANT SELECT ON board_club.genre TO 'club_host'@'%';
GRANT SELECT ON board_club.game  TO 'club_host'@'%';
GRANT SELECT ON board_club.game_table TO 'club_host'@'%';
GRANT SELECT (id, full_name, role) ON board_club.staff TO 'club_host'@'%';
GRANT SELECT, INSERT, UPDATE ON board_club.player TO 'club_host'@'%';
GRANT SELECT, UPDATE ON board_club.session TO 'club_host'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON board_club.session_player TO 'club_host'@'%';
GRANT SELECT ON board_club.v_player_rating  TO 'club_host'@'%';
GRANT SELECT ON board_club.v_player_history TO 'club_host'@'%';
GRANT EXECUTE ON PROCEDURE board_club.sp_create_session TO 'club_host'@'%';
GRANT EXECUTE ON PROCEDURE board_club.sp_start_session  TO 'club_host'@'%';
GRANT EXECUTE ON PROCEDURE board_club.sp_finish_session TO 'club_host'@'%';

GRANT SELECT ON board_club.v_player_rating  TO 'club_viewer'@'%';
GRANT SELECT ON board_club.v_player_history TO 'club_viewer'@'%';

FLUSH PRIVILEGES;

-- ============================================================
--  ТЕСТОВЫЕ ДАННЫЕ
-- ============================================================
INSERT INTO genre (name) VALUES ('Стратегия'), ('Пати'), ('Кооператив'), ('Карточная'), ('Семейная');

INSERT INTO game_table (number, capacity, description) VALUES
 (1, 4, 'Стол у входа'),
 (2, 4, 'Стол у окна'),
 (3, 6, 'Стол в центре зала'),
 (4, 6, 'Стол на веранде'),
 (5, 8, 'Большой стол (для пати-игр)');

INSERT INTO game (genre_id, title, min_players, max_players, duration_min, complexity, copies) VALUES
 (1, 'Каркассон',           2, 5,  45, 2, 2),
 (1, 'Колонизаторы',        3, 4,  90, 2, 1),
 (1, 'Билет на поезд',      2, 5,  60, 2, 1),
 (2, 'Кодовые имена',       4, 8,  20, 1, 2),
 (2, 'Имаджинариум',        3, 7,  45, 1, 1),
 (3, 'Пандемия',            2, 4,  60, 3, 1),
 (4, 'Уно',                 2, 10, 20, 1, 3),
 (5, 'Каркассон: Охотники', 2, 5,  40, 2, 1);

-- Пароли: admin / admin123, host / host123 (pbkdf2_sha256)
INSERT INTO staff (full_name, login, password_hash, role) VALUES
 ('Анна Администратор', 'admin',
  'pbkdf2_sha256$100000$5577be38723fd1259871bb082268c677$869656a504879a8af47507d4e6e9d23e39c9a61b214b10f852372e05e00772bd', 'admin'),
 ('Иван Ведущий', 'host',
  'pbkdf2_sha256$100000$8909e689363b03cc336539be89d77e51$37e3e007f4058dbb6077584cb0058dec944eec354caddde24bf1a29f9648c293', 'host');

INSERT INTO player (name, nickname, registered_at) VALUES
 ('Алексей Смирнов',  'meeple_king', '2026-06-01'),
 ('Мария Иванова',    'dice_queen',  '2026-06-03'),
 ('Дмитрий Козлов',   'dkoz',        '2026-06-10'),
 ('Екатерина Орлова', 'katya_o',     '2026-06-15'),
 ('Павел Волков',     'wolf',        '2026-07-01'),
 ('Ольга Новикова',   'olga_n',      '2026-07-05'),
 ('Сергей Морозов',   'frost',       '2026-07-20'),
 ('Наталья Лебедева', 'swan',        '2026-08-02');

-- Партия 1 (завершена)
CALL sp_create_session(1, 1, 2, '2026-09-05 18:00', '2026-09-05 19:00', '[1, 2, 3, 4]');
SET @s = LAST_INSERT_ID();
CALL sp_start_session(@s);
UPDATE session_player SET score = CASE player_id WHEN 1 THEN 112 WHEN 2 THEN 98 WHEN 3 THEN 87 ELSE 64 END
 WHERE session_id = @s;
CALL sp_finish_session(@s);
UPDATE session_player SET attended = TRUE WHERE session_id = @s;

-- Партия 2 (завершена)
CALL sp_create_session(4, 5, 2, '2026-09-12 19:00', '2026-09-12 19:30', '[2, 4, 5, 6, 7, 8]');
SET @s = LAST_INSERT_ID();
CALL sp_start_session(@s);
UPDATE session_player SET score = CASE player_id WHEN 2 THEN 9 WHEN 4 THEN 9 WHEN 5 THEN 6
                                               WHEN 6 THEN 5 WHEN 7 THEN 4 ELSE 2 END
 WHERE session_id = @s;
CALL sp_finish_session(@s);
-- Один игрок "не пришёл" — для демонстрации
UPDATE session_player SET attended = TRUE WHERE session_id = @s;
UPDATE session_player SET attended = FALSE WHERE session_id = @s AND player_id = 8;

-- Партия 3 (завершена)
CALL sp_create_session(6, 2, 1, '2026-09-19 17:00', '2026-09-19 18:30', '[1, 3, 5]');
SET @s = LAST_INSERT_ID();
CALL sp_start_session(@s);
UPDATE session_player SET score = CASE player_id WHEN 1 THEN 3 WHEN 3 THEN 7 ELSE 5 END
 WHERE session_id = @s;
CALL sp_finish_session(@s);
UPDATE session_player SET attended = TRUE WHERE session_id = @s;

-- Партия 4 (запланирована)
CALL sp_create_session(2, 3, 2, '2026-10-03 18:00', '2026-10-03 19:30', '[2, 6, 7]');