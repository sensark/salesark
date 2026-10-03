import re
from decimal import Decimal

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from erp.models import ApprovalRule, ROLE_ADMIN, ROLE_SALES_MANAGER, ROLES, User
from erp.permissions import require_action

MIN_PASSWORD_LENGTH = 8
USERNAME_RE = re.compile(r"^[a-z0-9._]{3,50}$")


class UserError(ValueError):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def list_users(session: Session, active_only: bool = False) -> list[User]:
    stmt = select(User).order_by(User.role, User.name)
    if active_only:
        stmt = stmt.where(User.active.is_(True))
    return list(session.scalars(stmt))


def get_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def create_user(session: Session, *, username: str, name: str, email: str, password: str, role: str) -> User:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        raise UserError("Username must be 3-50 characters: letters, numbers, dots or underscores.")
    if role not in ROLES:
        raise UserError("Invalid role.")
    if not name.strip() or "@" not in email:
        raise UserError("Name and a valid email are required.")
    _check_password(password)
    if get_by_username(session, username):
        raise UserError("That username is already taken.")
    user = User(username=username, name=name.strip(), email=email.strip().lower(),
                password_hash=hash_password(password), role=role, active=True)
    session.add(user)
    session.flush()
    return user


def create_first_admin(
    session: Session,
    *,
    username: str,
    name: str,
    email: str,
    password: str,
) -> User:
    existing_user_id = session.scalar(select(User.id).limit(1).with_for_update())
    if existing_user_id is not None:
        raise UserError("Initial setup is already complete. Sign in instead.")
    return create_user(
        session, username=username, name=name, email=email,
        password=password, role=ROLE_ADMIN,
    )


def set_password(session: Session, user_id: int, password: str) -> None:
    _check_password(password)
    user = session.get(User, user_id)
    if user is None:
        raise UserError("User not found.")
    user.password_hash = hash_password(password)


def set_active(session: Session, user_id: int, active: bool, acting_user_id: int) -> None:
    if user_id == acting_user_id and not active:
        raise UserError("You cannot deactivate your own account.")
    user = session.get(User, user_id)
    if user is None:
        raise UserError("User not found.")
    user.active = active


def list_approval_rules(session: Session) -> list[ApprovalRule]:
    return list(session.scalars(select(ApprovalRule).order_by(ApprovalRule.rule_type, ApprovalRule.name)))


def save_approval_rule(
    session: Session,
    *,
    actor_id: int,
    name: str,
    rule_type: str,
    threshold: Decimal,
    approver_role: str,
    active: bool = True,
    rule_id: int | None = None,
) -> ApprovalRule:
    actor = session.get(User, actor_id)
    if actor is None:
        raise UserError("Admin user not found.")
    try:
        require_action(actor.role, "settings.manage")
    except PermissionError as exc:
        raise UserError(str(exc)) from exc
    if rule_type not in {"ORDER_VALUE", "DISCOUNT_PCT"}:
        raise UserError("Choose an order-value or discount-percent rule.")
    if threshold <= 0:
        raise UserError("Rule threshold must be greater than zero.")
    if approver_role not in {ROLE_ADMIN, ROLE_SALES_MANAGER}:
        raise UserError("Order approver must be a Sales Manager or Admin / Owner.")
    name = name.strip()
    if not name:
        raise UserError("Rule name is required.")
    rule = session.get(ApprovalRule, rule_id) if rule_id else ApprovalRule()
    rule.name = name
    rule.rule_type = rule_type
    rule.threshold = threshold
    rule.approver_role = approver_role
    rule.active = active
    session.add(rule)
    session.flush()
    from erp.services.audit import record

    record(
        session, actor_id=actor.id, action="SAVE", entity_type="APPROVAL_RULE",
        entity_id=rule.id, changes={"type": rule_type, "threshold": threshold,
                                    "approver_role": approver_role, "active": active},
    )
    return rule
