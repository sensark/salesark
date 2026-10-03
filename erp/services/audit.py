import json
from typing import Any

from sqlalchemy.orm import Session

from erp.models import SalesAuditLog


def record(
    session: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int,
    changes: dict[str, Any] | None = None,
) -> SalesAuditLog:
    entry = SalesAuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changes_json=json.dumps(changes or {}, sort_keys=True, default=str),
    )
    session.add(entry)
    return entry