from fastapi import APIRouter

router = APIRouter()


@router.get("/items")
def list_items() -> list[dict[str, int | str]]:
    return [{"id": 1, "name": "demo"}]
