"""Administrative ledger reads from actual balance transactions."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from auth.deps import AuthContext, require_roles, require_super_admin
from controllers.billing import billing_scope
from models.usage_record import ModelUsageRecord
from schemas.billing import ModelUsageRecordOut
from services.billing.aggregation import summary
from schemas.billing import StatementFilters, StatementOut, StatementPartiesOut, StatementQuery
from services.billing.statements import billing_statements
from utils.response_format import ResponseSchema

router = APIRouter()


async def statement_admin(ctx: AuthContext = Depends(require_super_admin)):
    if not ctx.is_super_admin:
        raise HTTPException(403, "Forbidden")
    return ctx


@router.get("/statements/parties", response_model=ResponseSchema[StatementPartiesOut])
async def parties(response: Response, ctx=Depends(statement_admin)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await billing_statements.parties())


@router.get("/statements", response_model=ResponseSchema[StatementOut])
async def statements(response: Response, filters: Annotated[StatementQuery, Query()], ctx=Depends(statement_admin)):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await billing_statements.list(filters, filters.page, filters.page_size))


@router.get("/statements/export")
async def export(filters: Annotated[StatementFilters, Query()], ctx=Depends(statement_admin)):
    return StreamingResponse(billing_statements.export(filters), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="billing-statement.csv"', "Cache-Control": "no-store"})


@router.get("/summary")
async def billing_summary(novel_id: int | None = None, ctx=Depends(require_roles("admin", "creator"))):
    return ResponseSchema(data=await summary(novel_id, *billing_scope(ctx)))


@router.get("/projects")
async def billing_projects(ctx=Depends(require_roles("admin", "creator"))):
    return ResponseSchema(data={"items": [], "pagination": {"total": 0, "page": 1, "page_size": 20, "pages": 0}})


@router.get("/records")
async def billing_records(page: int = 1, page_size: int = 20, ctx=Depends(require_roles("admin", "creator"))):
    team_id, user_id = billing_scope(ctx)
    query = ModelUsageRecord.all()
    if team_id is not None:
        query = query.filter(team_id=team_id)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    page, page_size = max(1, page), max(1, min(100, page_size))
    total = await query.count()
    rows = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return ResponseSchema(data={"items": [ModelUsageRecordOut.model_validate(row) for row in rows],
        "pagination": {"total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}})
