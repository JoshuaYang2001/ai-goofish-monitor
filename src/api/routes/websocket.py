"""
WebSocket 路由
提供实时通信功能
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, Set

from src.services.auth_service import verify_access_token
from src.tenancy.context import tenant_scope


router = APIRouter()

# 全局 WebSocket 连接管理
active_connections: Dict[str, Set[WebSocket]] = {}


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    """WebSocket 端点"""
    token = websocket.query_params.get("token", "")
    try:
        identity = verify_access_token(token)
    except ValueError:
        await websocket.close(code=4401)
        return
    tenant_connections = active_connections.setdefault(identity.tenant_id, set())
    # 接受连接
    await websocket.accept()
    tenant_connections.add(websocket)

    try:
        # 保持连接并接收消息
        while True:
            # 接收客户端消息（如果有的话）
            data = await websocket.receive_text()
            # 这里可以处理客户端发送的消息
            # 目前我们主要用于服务端推送，所以暂时不处理
    except WebSocketDisconnect:
        tenant_connections.discard(websocket)
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        tenant_connections.discard(websocket)
    finally:
        if not tenant_connections:
            active_connections.pop(identity.tenant_id, None)


async def broadcast_message(message_type: str, data: dict):
    """仅向当前租户的连接广播消息。"""
    from src.tenancy.context import current_tenant_id

    tenant_id = current_tenant_id(required=False)
    message = {
        "type": message_type,
        "data": data
    }

    # 移除已断开的连接
    disconnected = set()

    tenant_connections = active_connections.get(tenant_id, set())
    for connection in tenant_connections:
        try:
            await connection.send_json(message)
        except Exception:
            disconnected.add(connection)

    # 清理断开的连接
    for connection in disconnected:
        tenant_connections.discard(connection)
