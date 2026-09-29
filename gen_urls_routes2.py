import re

src = open('admin/app.py').read()

# Find existing urls_page function
pattern = r'@app\.route\("/urls"\).*?(?=@app\.route|# ROUTES —|if __name__)'
match = re.search(pattern, src, re.DOTALL)

if not match:
    print("FAIL: urls_page not found")
else:
    new_func = '''@app.route("/urls")
@require_login
def urls_page():
    mode = request.args.get("mode", "url_date")
    search = request.args.get("search", "").strip()
    expand_url = request.args.get("expand", "").strip()
    expand_date = request.args.get("expand_date", "").strip()

    # ─── SUMMARY LIST ───
    if mode == "url":
        sql = ("""SELECT url,
                         COUNT(*) as total_orders,
                         COALESCE(SUM(deposit),0) as total_deposit,
                         COALESCE(SUM(withdrawal),0) as total_withdrawal,
                         COALESCE(SUM(reward),0) as total_reward,
                         COUNT(DISTINCT DATE(created_at)) as days_active
                  FROM orders WHERE url IS NOT NULL AND url != ''""")
        params = []
        if search:
            sql += " AND url LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY url ORDER BY total_orders DESC LIMIT 200"
        rows = q_all(sql, tuple(params))

        urls_data = []
        for r in rows:
            urls_data.append({
                "url": r[0], "date": None,
                "orders": r[1], "deposit": r[2], "withdrawal": r[3],
                "reward": r[4], "days": r[5]
            })
    else:
        sql = ("""SELECT url, DATE(created_at) as d,
                         COUNT(*) as total_orders,
                         COALESCE(SUM(deposit),0) as total_deposit,
                         COALESCE(SUM(withdrawal),0) as total_withdrawal,
                         COALESCE(SUM(reward),0) as total_reward
                  FROM orders WHERE url IS NOT NULL AND url != ''""")
        params = []
        if search:
            sql += " AND url LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY url, DATE(created_at) ORDER BY d DESC, total_orders DESC LIMIT 200"
        rows = q_all(sql, tuple(params))

        urls_data = []
        for r in rows:
            urls_data.append({
                "url": r[0], "date": r[1],
                "orders": r[2], "deposit": r[3], "withdrawal": r[4],
                "reward": r[5], "days": None
            })

    # ─── EXPANDED VIEW (user-wise) ───
    expand_data = None
    expand_users = []

    if expand_url:
        if expand_date:
            user_rows = q_all(
                """SELECT u.id, u.name, u.mobile, u.account_no,
                          COUNT(o.id) as orders_cnt,
                          COALESCE(SUM(o.deposit),0) as total_dep,
                          COALESCE(SUM(o.withdrawal),0) as total_wd,
                          COALESCE(SUM(o.reward),0) as total_rw
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE o.url = ? AND DATE(o.created_at) = ?
                   GROUP BY u.id
                   ORDER BY total_rw DESC""",
                (expand_url, expand_date)
            )
            uids = q_all(
                "SELECT DISTINCT game_uid FROM orders WHERE url=? AND DATE(created_at)=? "
                "AND game_uid IS NOT NULL AND game_uid != ''",
                (expand_url, expand_date)
            )
        else:
            user_rows = q_all(
                """SELECT u.id, u.name, u.mobile, u.account_no,
                          COUNT(o.id) as orders_cnt,
                          COALESCE(SUM(o.deposit),0) as total_dep,
                          COALESCE(SUM(o.withdrawal),0) as total_wd,
                          COALESCE(SUM(o.reward),0) as total_rw
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE o.url = ?
                   GROUP BY u.id
                   ORDER BY total_rw DESC""",
                (expand_url,)
            )
            uids = q_all(
                "SELECT DISTINCT game_uid FROM orders WHERE url=? "
                "AND game_uid IS NOT NULL AND game_uid != ''",
                (expand_url,)
            )

        # Per-user UIDs
        for row in user_rows:
            uid = row[0]
            if expand_date:
                user_uids = q_all(
                    "SELECT DISTINCT game_uid FROM orders WHERE user_id=? AND url=? AND DATE(created_at)=? "
                    "AND game_uid IS NOT NULL AND game_uid != ''",
                    (uid, expand_url, expand_date)
                )
            else:
                user_uids = q_all(
                    "SELECT DISTINCT game_uid FROM orders WHERE user_id=? AND url=? "
                    "AND game_uid IS NOT NULL AND game_uid != ''",
                    (uid, expand_url)
                )
            expand_users.append({
                "id": row[0], "name": row[1], "mobile": row[2], "account_no": row[3],
                "orders": row[4], "deposit": row[5], "withdrawal": row[6], "reward": row[7],
                "uids": [u[0] for u in user_uids]
            })

        expand_data = {
            "url": expand_url,
            "date": expand_date or None,
            "total_uids": [u[0] for u in uids]
        }

    return render_template("urls.html",
                           urls_data=urls_data, mode=mode, search=search,
                           expand_url=expand_url, expand_date=expand_date,
                           expand_data=expand_data, expand_users=expand_users,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


'''
    src = src[:match.start()] + new_func + src[match.end():]
    open('admin/app.py', 'w').write(src)
    print("✅ urls_page upgraded")


'''

if False:
    pass
'''

