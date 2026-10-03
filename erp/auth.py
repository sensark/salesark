from dataclasses import dataclass

import streamlit as st
import streamlit_authenticator as stauth

from erp import config
from erp.db import session_scope
from erp.models import ROLE_ADMIN
from erp.permissions import ROLE_LABELS
from erp.services import users as user_service


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    name: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


def _credentials() -> dict:
    with session_scope() as session:
        active = user_service.list_users(session, active_only=True)
        return {
            "usernames": {
                u.username: {
                    "email": u.email,
                    "first_name": u.name.split(" ")[0],
                    "last_name": " ".join(u.name.split(" ")[1:]),
                    "name": u.name,
                    "password": u.password_hash,
                    "roles": [u.role],
                }
                for u in active
            }
        }


def get_authenticator() -> stauth.Authenticate:
    return stauth.Authenticate(
        _credentials(),
        cookie_name=config.AUTH_COOKIE_NAME,
        cookie_key=config.AUTH_COOKIE_KEY,
        cookie_expiry_days=config.AUTH_COOKIE_EXPIRY_DAYS,
        auto_hash=False,
    )


def load_current_user() -> CurrentUser | None:
    """Resolve the logged-in user from the database so role and active flag are always current."""
    if not st.session_state.get("authentication_status"):
        st.session_state.pop("current_user", None)
        return None
    username = st.session_state.get("username")
    with session_scope() as session:
        user = user_service.get_by_username(session, username) if username else None
        if user is None or not user.active:
            st.session_state.pop("current_user", None)
            return None
        current = CurrentUser(user.id, user.username, user.name, user.email, user.role)
    st.session_state["current_user"] = current
    return current


def current_user() -> CurrentUser:
    user = st.session_state.get("current_user")
    if user is None:
        st.error("Your session has expired. Please sign in again.")
        st.stop()
    return user


def require_role(*roles: str) -> CurrentUser:
    user = current_user()
    if user.role not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()
    return user
