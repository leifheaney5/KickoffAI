#!/usr/bin/env python3
"""
Account — sign in, and (for admins) manage who can use this club install.

Club features are opt-in. With no users defined the app is unrestricted and
behaves exactly as a single-coach install always has; creating the first user
turns authentication on for everyone and makes that user the admin.
"""

import streamlit as st

import auth
import brand
import db

st.markdown(brand.app_css(), unsafe_allow_html=True)
st.markdown(brand.page_header("CLUB", "Account"), unsafe_allow_html=True)

enabled = auth.auth_enabled()
me = auth.current_user()

# --------------------------------------------------------------------------- #
# Single-coach install: nothing to sign in to yet
# --------------------------------------------------------------------------- #
if not enabled:
    st.info("This install has no accounts, so nothing is locked. Everything "
            "works exactly as it does for a single coach.")
    st.markdown(brand.section("Turn on club mode"), unsafe_allow_html=True)
    st.caption("Creating the first account enables sign-in for everyone using "
               "this install and makes that account the administrator. Matches "
               "captured from then on are stamped with their owner.")
    with st.form("bootstrap"):
        c1, c2 = st.columns(2)
        username = c1.text_input("Username")
        display = c2.text_input("Display name", placeholder="Leif Heaney")
        p1 = c1.text_input("Password", type="password")
        p2 = c2.text_input("Confirm password", type="password")
        if st.form_submit_button("Create administrator account",
                                 type="primary", width="stretch"):
            if p1 != p2:
                st.error("The passwords do not match.")
            else:
                try:
                    user = auth.create_user(username, p1, display)
                    auth.start_session(user)
                    st.success(f"Welcome, {user['display_name']}.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    st.stop()

# --------------------------------------------------------------------------- #
# Sign in
# --------------------------------------------------------------------------- #
if not me:
    st.markdown(brand.section("Sign in"), unsafe_allow_html=True)
    with st.form("signin"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            user = auth.authenticate(username, password)
            if user:
                auth.start_session(user)
                st.rerun()
            else:
                # Deliberately does not say which of the two was wrong.
                st.error("Incorrect username or password.")
    st.stop()

# --------------------------------------------------------------------------- #
# Signed in
# --------------------------------------------------------------------------- #
st.markdown(brand.section("Signed in"), unsafe_allow_html=True)
c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="center")
c1.markdown(f"**{me['display_name']}** · `{me['username']}`")
c2.metric("Role", me["role"].title())
if c3.button("Sign out", width="stretch"):
    auth.end_session()
    st.rerun()

st.markdown(brand.section("Change your password"), unsafe_allow_html=True)
with st.form("change_pw"):
    cur = st.text_input("Current password", type="password")
    new1 = st.text_input("New password", type="password")
    new2 = st.text_input("Confirm new password", type="password")
    if st.form_submit_button("Update password", width="stretch"):
        if not auth.authenticate(me["username"], cur):
            st.error("Your current password is not correct.")
        elif new1 != new2:
            st.error("The new passwords do not match.")
        else:
            try:
                auth.set_password(me["username"], new1)
                st.success("Password updated.")
            except ValueError as exc:
                st.error(str(exc))

# --------------------------------------------------------------------------- #
# Club sync
#
# Capture never depends on the server: matches archive locally first and push
# when there happens to be a connection. Being offline is normal, not an error.
# --------------------------------------------------------------------------- #
import sync  # noqa: E402

st.divider()
st.markdown(brand.section("Club sync"), unsafe_allow_html=True)
sy = sync.status()

if not sy["configured"]:
    st.caption("No club server configured. Matches are archived to this machine "
               "only. To share a library, set `KICKOFF_SHARED_DB_URL` to the "
               "club's Postgres.")
else:
    s1, s2, s3 = st.columns([1, 1, 2], vertical_alignment="center")
    s1.metric("Server", "Reachable" if sy["reachable"] else "Offline")
    s2.metric("Waiting to sync", sy["pending"])
    s3.caption(f"`{sy['server']}`")
    if not sy["reachable"]:
        st.info(f"{sy['detail']} Matches stay safely on this machine and will "
                "push when the server is reachable — nothing is lost.")

    if sy["pending"]:
        st.dataframe(
            [{"Match": m["name"], "Played": m["played_on"],
              "Events": m["events"], "State": m["sync_state"].title()}
             for m in sy["matches"]], width="stretch", hide_index=True)

    if st.button("Push matches to the club library", type="primary",
                 width="stretch", disabled=not (sy["reachable"] and sy["pending"])):
        with st.spinner("Pushing…"):
            res = sync.push()
        if res.get("ok"):
            st.success(f"Pushed {res['pushed']} match(es).")
            failed = [r for r in res["results"] if r["action"] == "failed"]
            for f in failed:
                st.error(f"{f['slug']}: {f.get('error', 'failed')}")
        else:
            st.warning(res.get("error", "Could not push."))
        st.rerun()

# --------------------------------------------------------------------------- #
# Admin: people and teams
# --------------------------------------------------------------------------- #
if not auth.is_admin(me):
    st.stop()

st.divider()
st.markdown(brand.section("People", "ADMIN"), unsafe_allow_html=True)
users = auth.list_users()
st.dataframe(
    [{"Username": u["username"], "Name": u["display_name"],
      "Role": u["role"].title(), "Active": u["active"]} for u in users],
    width="stretch", hide_index=True)

with st.expander("Add someone"):
    with st.form("add_user"):
        a1, a2 = st.columns(2)
        nu = a1.text_input("Username", key="nu")
        nd = a2.text_input("Display name", key="nd")
        np1 = a1.text_input("Password", type="password", key="np1")
        nr = a2.selectbox("Role", list(auth.ROLES), index=1)
        if st.form_submit_button("Create account", type="primary",
                                 width="stretch"):
            try:
                auth.create_user(nu, np1, nd, nr)
                st.success(f"Created {nu}.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

st.markdown(brand.section("Teams", "ADMIN"), unsafe_allow_html=True)
st.caption("Matches belong to a team so the library and season can be scoped to "
           "the sides a coach actually works with.")

db.init_db()
with db.session() as s:
    teams = [{"id": str(t.id), "slug": t.slug, "name": t.name}
             for t in s.query(db.Team).order_by(db.Team.name).all()]
    members = {}
    for tm in s.query(db.TeamMember).all():
        members.setdefault(str(tm.team_id), []).append(str(tm.user_id))

if teams:
    by_id = {u["id"]: u["username"] for u in users}
    st.dataframe(
        [{"Team": t["name"], "Slug": t["slug"],
          "Members": ", ".join(sorted(by_id.get(m, "?")
                                      for m in members.get(t["id"], []))) or "—"}
         for t in teams], width="stretch", hide_index=True)
else:
    st.caption("No teams yet.")

with st.expander("Add a team"):
    with st.form("add_team"):
        tname = st.text_input("Team name", placeholder="U14 Eagles")
        if st.form_submit_button("Create team", type="primary", width="stretch"):
            import re
            slug = re.sub(r"[^a-z0-9]+", "-", (tname or "").lower()).strip("-")
            if not slug:
                st.error("Give the team a name.")
            else:
                with db.session() as s:
                    if s.query(db.Team).filter_by(slug=slug).first():
                        st.error("A team with that name already exists.")
                    else:
                        s.add(db.Team(slug=slug, name=tname.strip()))
                        st.success(f"Created {tname}.")
                        st.rerun()

if teams and users:
    with st.expander("Put someone in a team"):
        m1, m2 = st.columns(2)
        who = m1.selectbox("Person", [u["username"] for u in users])
        which = m2.selectbox("Team", [t["name"] for t in teams])
        if st.button("Add to team", width="stretch"):
            # Ids are strings in these dicts; the columns are UUID-typed.
            uid = auth.as_uuid(next(u["id"] for u in users if u["username"] == who))
            tid = auth.as_uuid(next(t["id"] for t in teams if t["name"] == which))
            with db.session() as s:
                exists = s.query(db.TeamMember).filter_by(
                    user_id=uid, team_id=tid).first()
                if exists:
                    st.info(f"{who} is already in {which}.")
                else:
                    s.add(db.TeamMember(user_id=uid, team_id=tid))
                    st.success(f"Added {who} to {which}.")
                    st.rerun()
