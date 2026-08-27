"""
WS 消息协议常量。

客户端 → 服务端：
  { "type": "message", "conversation_id": <int>, "content": <str> }
  { "type": "pong" }   // 心跳响应
  { "type": "diary", "date": <str> }   // 用户写/拉日记（InboundHub 未注册前忽略）

服务端 → 客户端：
  { "type": "message", "conversation_id": <int>, "msg": {id, role, content, time} }
  { "type": "typing", "conversation_id": <int> }
  { "type": "system", "content": <str> }
  { "type": "active", "conversation_id": <int>, "msg": {...} }  // 主动消息（日终总结等）
  { "type": "diary_push", "diary": {id, content, time} }        // 日终日记主动推送
  { "type": "ping" }   // 心跳
"""

# 客户端 → 服务端
TYPE_MESSAGE = "message"
TYPE_PONG = "pong"
TYPE_DIARY = "diary"         # 用户写/拉日记（预留，接入 InboundHub 后启用）

# 服务端 → 客户端
TYPE_MSG = "message"
TYPE_TYPING = "typing"
TYPE_SYSTEM = "system"
TYPE_ACTIVE = "active"
TYPE_DIARY_PUSH = "diary_push"   # 日终日记主动推送
TYPE_PING = "ping"