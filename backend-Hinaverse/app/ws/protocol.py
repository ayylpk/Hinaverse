"""
WS 消息协议常量。

客户端 → 服务端：
  { "type": "message", "conversation_id": <int>, "content": <str> }
  { "type": "pong" }   // 心跳响应

服务端 → 客户端：
  { "type": "message", "conversation_id": <int>, "msg": {id, role, content, time} }
  { "type": "typing", "conversation_id": <int> }
  { "type": "system", "content": <str> }
  { "type": "active", "conversation_id": <int>, "msg": {...} }  // 主动消息
  { "type": "ping" }   // 心跳
"""

# 客户端 → 服务端
TYPE_MESSAGE = "message"
TYPE_PONG = "pong"

# 服务端 → 客户端
TYPE_MSG = "message"
TYPE_TYPING = "typing"
TYPE_SYSTEM = "system"
TYPE_ACTIVE = "active"
TYPE_PING = "ping"
