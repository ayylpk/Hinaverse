-- 阶段 4：主动关心消息队列 —— send_messages 改造（2026-09-01）
-- 执行（服务器）：docker exec -i $(docker ps -qf name=mysql) mysql -uroot -p'<MYSQL_ROOT_PASSWORD>' hinaverse < send_messages_queue_20260901.sql
--   （密码见服务器 agentmemory 目录 .env 的 MYSQL_ROOT_PASSWORD，勿写进本文件）
-- 执行（本机开发库 hinaverse / 测试库 hinaverse_test 同理换库名）

ALTER TABLE send_messages
  ADD COLUMN scheduled_at DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00' AFTER content,
  ADD COLUMN status ENUM('pending','sent','cancelled','expired') NOT NULL DEFAULT 'pending' AFTER scheduled_at,
  ADD COLUMN fail_count INT NOT NULL DEFAULT 0 AFTER status,
  ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP AFTER fail_count,
  ADD INDEX idx_due (status, scheduled_at);

-- 历史孤儿行（旧接口塞的、没有送达时间的）：一律 cancelled，防止被扫描当成到点消息发出去
UPDATE send_messages SET status = 'cancelled' WHERE scheduled_at = '1970-01-01 00:00:00';
