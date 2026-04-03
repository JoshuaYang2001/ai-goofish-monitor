"""
卖家管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.services.seller_monitoring_service import get_seller_service

router = APIRouter(prefix="/api/sellers", tags=["sellers"])


class SellerListRequest(BaseModel):
    seller_id: str
    reason: str = ""


class SellerIdSearchRequest(BaseModel):
    item_id: str


@router.get("/{seller_id}")
async def get_seller_info(seller_id: str):
    """获取卖家信息"""
    service = get_seller_service()
    info = service.get_seller_info(seller_id)
    if not info:
        raise HTTPException(status_code=404, detail="卖家信息不存在")
    return info


@router.post("/blacklist")
async def add_to_blacklist(request: SellerListRequest):
    """添加卖家到黑名单"""
    service = get_seller_service()
    service.add_to_blacklist(request.seller_id, reason=request.reason)
    return {"success": True, "message": "已添加到黑名单"}


@router.post("/whitelist")
async def add_to_whitelist(request: SellerListRequest):
    """添加卖家到白名单"""
    service = get_seller_service()
    service.add_to_whitelist(request.seller_id, reason=request.reason)
    return {"success": True, "message": "已添加到白名单"}


@router.delete("/list/{seller_id}")
async def remove_from_list(seller_id: str):
    """从黑名单/白名单移除卖家"""
    service = get_seller_service()
    service.remove_from_list(seller_id)
    return {"success": True, "message": "已从列表移除"}


@router.get("/blacklist/list")
async def get_blacklist() -> List[dict]:
    """获取黑名单列表"""
    service = get_seller_service()
    return service.get_blacklist()


@router.get("/whitelist/list")
async def get_whitelist() -> List[dict]:
    """获取白名单列表"""
    service = get_seller_service()
    return service.get_whitelist()


@router.post("/search/item-id")
async def search_by_item_id(request: SellerIdSearchRequest):
    """通过商品 ID 精确搜索商品"""
    from src.scraper import scrape_item_by_id

    service = get_seller_service()
    try:
        result = await scrape_item_by_id(request.item_id)
        if result:
            service.save_search_history(request.item_id, result)
            return {"success": True, "data": result}
        else:
            raise HTTPException(status_code=404, detail="商品不存在或已下架")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search-history")
async def get_search_history(limit: int = 20):
    """获取商品 ID 搜索历史"""
    service = get_seller_service()
    return {"history": service.get_search_history(limit=limit)}
