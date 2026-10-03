from html import escape

import streamlit as st

from erp.auth import current_user
from erp.db import session_scope
from erp.services import notifications
from erp.ui.components import page_header

user = current_user()
page_header("Notifications", "Order updates and approval requests.", user.role_label)

with session_scope() as session:
    items = notifications.list_for(session, user.id, limit=100)
    unread = sum(not n.is_read for n in items)

c1, c2 = st.columns([4, 1])
c1.markdown(f"**{unread}** unread")
if c2.button("Mark all as read", width="stretch", disabled=unread == 0):
    with session_scope() as session:
        notifications.mark_all_read(session, user.id)
    st.rerun()

if not items:
    st.info("You have no notifications yet.")
for n in items:
    border = "#FF7A00" if not n.is_read else "#D7DEEA"
    weight = 700 if not n.is_read else 400
    st.markdown(
        f"""<div style="background:#FFFFFF;border:1px solid #E3E8F0;border-left:5px solid {border};
        border-radius:10px;padding:12px 16px;margin-bottom:8px;">
        <div style="font-weight:{weight};color:#0B1F3A">{escape(n.message)}</div>
        <div style="font-size:12px;color:#5B6B82;margin-top:4px">{n.created_at:%d %b %Y %H:%M}</div></div>""",
        unsafe_allow_html=True,
    )
