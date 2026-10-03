from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from erp.models import ROLE_ADMIN, ROLE_SALES_MANAGER, Notification, User


def notify(session: Session, user_id: int, message: str, order_id: int | None = None) -> None:
    session.add(Notification(user_id=user_id, message=message, order_id=order_id))


def notify_admins(session: Session, message: str, order_id: int | None = None) -> None:
    admin_ids = session.scalars(select(User.id).where(User.role == ROLE_ADMIN, User.active.is_(True)))
    for admin_id in admin_ids:
        notify(session, admin_id, message, order_id)


def notify_approvers(
    session: Session,
    required_role: str,
    message: str,
    order_id: int | None = None,
) -> None:
    roles = [ROLE_ADMIN] if required_role == ROLE_ADMIN else [ROLE_ADMIN, ROLE_SALES_MANAGER]
    user_ids = session.scalars(
        select(User.id).where(User.role.in_(roles), User.active.is_(True))
    )
    for user_id in user_ids:
        notify(session, user_id, message, order_id)


def unread_count(session: Session, user_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
    ) or 0


def list_for(session: Session, user_id: int, limit: int = 30) -> list[Notification]:
    return list(
        session.scalars(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def mark_all_read(session: Session, user_id: int) -> None:
    session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
