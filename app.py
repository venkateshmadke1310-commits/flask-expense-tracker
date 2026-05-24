import sqlite3
from flask import Flask, render_template, request, redirect, session, Response
from datetime import datetime

app = Flask(__name__)
app.secret_key = "expense_tracker_secret"

def get_db_connection():
    conn = sqlite3.connect("expenses.db")
    conn.row_factory = sqlite3.Row
    return conn

def log_user_activity(username, activity, ip_address=None):
    """Log user activity for analytics"""
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_activity (username, activity, timestamp, ip_address)
        VALUES (?, ?, ?, ?)
    """, (username, activity, datetime.now().isoformat(), ip_address or request.remote_addr))
    conn.commit()
    conn.close()

def setup_database():
    conn = sqlite3.connect("expenses.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        category TEXT,
        description TEXT,
        date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS limits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        category TEXT,
        limit_amount REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS user_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        activity TEXT,
        timestamp TEXT,
        ip_address TEXT
    )
    """)

    conn.commit()
    conn.close()

setup_database()

@app.route("/")
def home():
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    category = request.args.get("category")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    query = "SELECT * FROM expenses WHERE user_id=?"
    total_query = "SELECT SUM(amount) FROM expenses WHERE user_id=?"
    params = [user_id]

    if category:
        query += " AND category=?"
        total_query += " AND category=?"
        params.append(category)
    if from_date:
        query += " AND date>=?"
        total_query += " AND date>=?"
        params.append(from_date)
    if to_date:
        query += " AND date<=?"
        total_query += " AND date<=?"
        params.append(to_date)

    query += " ORDER BY date DESC"

    conn = get_db_connection()
    expenses = conn.execute(query, params).fetchall()
    total = conn.execute(total_query, params).fetchone()[0] or 0
    conn.close()

    return render_template("view.html", expenses=expenses, total=total)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, request.form["password"])
            )
            conn.commit()
            log_user_activity(username, "REGISTERED")
        except sqlite3.IntegrityError:
            conn.close()
            return "Username already exists"
        conn.close()
        return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, request.form["password"])
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            log_user_activity(username, "LOGGED_IN")
            return redirect("/")
        log_user_activity(username, "FAILED_LOGIN")
        return "Invalid login"

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/add", methods=["GET", "POST"])
def add():
    if "user_id" not in session:
        return redirect("/login")

    error = None

    if request.method == "POST":
        amount = float(request.form["amount"])
        category = request.form["category"]

        conn = get_db_connection()
        limit_row = conn.execute(
            "SELECT limit_amount FROM limits WHERE user_id=? AND category=?",
            (session["user_id"], category)
        ).fetchone()

        if limit_row:
            current_total = conn.execute(
                "SELECT SUM(amount) FROM expenses WHERE user_id=? AND category=?",
                (session["user_id"], category)
            ).fetchone()[0] or 0

            if current_total + amount > limit_row["limit_amount"]:
                conn.close()
                error = f"Expense limit exceeded for {category}. Limit: ₹{limit_row['limit_amount']}"
                return render_template("add.html", error=error)

        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, description, date) VALUES (?, ?, ?, ?, ?)",
            (
                session["user_id"],
                amount,
                category,
                request.form["description"],
                request.form["date"]
            )
        )
        conn.commit()
        conn.close()
        return redirect("/")

    return render_template("add.html", error=error)

@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    expense = conn.execute(
        "SELECT * FROM expenses WHERE id=? AND user_id=?",
        (id, session["user_id"])
    ).fetchone()

    if not expense:
        conn.close()
        return "Not allowed", 403

    error = None

    if request.method == "POST":
        amount = float(request.form["amount"])
        category = request.form["category"]

        limit_row = conn.execute(
            "SELECT limit_amount FROM limits WHERE user_id=? AND category=?",
            (session["user_id"], category)
        ).fetchone()

        if limit_row:
            current_total = conn.execute(
                "SELECT SUM(amount) FROM expenses WHERE user_id=? AND category=? AND id!=?",
                (session["user_id"], category, id)
            ).fetchone()[0] or 0

            if current_total + amount > limit_row["limit_amount"]:
                conn.close()
                error = f"Expense limit exceeded for {category}. Limit: ₹{limit_row['limit_amount']}"
                return render_template("edit.html", expense=expense, error=error)

        conn.execute(
            "UPDATE expenses SET amount=?, category=?, description=?, date=? WHERE id=? AND user_id=?",
            (
                amount,
                category,
                request.form["description"],
                request.form["date"],
                id,
                session["user_id"]
            )
        )
        conn.commit()
        conn.close()
        return redirect("/")

    conn.close()
    return render_template("edit.html", expense=expense)

@app.route("/delete/<int:id>", methods=["POST"])
def delete(id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    conn.execute(
        "DELETE FROM expenses WHERE id=? AND user_id=?",
        (id, session["user_id"])
    )
    conn.commit()
    conn.close()
    return redirect("/")

@app.route("/summary")
def summary():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    data = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses WHERE user_id=? GROUP BY category",
        (session["user_id"],)
    ).fetchall()
    conn.close()

    return render_template("summary.html", summary=data)

@app.route("/monthly")
def monthly_summary():
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    data = conn.execute("""
        SELECT strftime('%Y-%m', date) AS month, SUM(amount) AS total
        FROM expenses
        WHERE user_id=?
        GROUP BY month
        ORDER BY month DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    return render_template("monthly.html", monthly=data)

@app.route("/export/<month>")
def export_month(month):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db_connection()
    expenses = conn.execute("""
        SELECT date, amount, category, description
        FROM expenses
        WHERE strftime('%Y-%m', date)=? AND user_id=?
        ORDER BY date
    """, (month, session["user_id"])).fetchall()
    conn.close()

    def generate():
        yield "Date,Amount,Category,Description\n"
        for e in expenses:
            yield f"{e['date']},{e['amount']},{e['category']},{e['description']}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=expenses_{month}.csv"}
    )

@app.route("/set_limit", methods=["GET", "POST"])
def set_limit():
    if "user_id" not in session:
        return redirect("/login")

    message = None

    if request.method == "POST":
        category = request.form["category"]
        limit_amount = float(request.form["limit"])

        conn = get_db_connection()
        existing = conn.execute(
            "SELECT * FROM limits WHERE user_id=? AND category=?",
            (session["user_id"], category)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE limits SET limit_amount=? WHERE user_id=? AND category=?",
                (limit_amount, session["user_id"], category)
            )
        else:
            conn.execute(
                "INSERT INTO limits (user_id, category, limit_amount) VALUES (?, ?, ?)",
                (session["user_id"], category, limit_amount)
            )

        conn.commit()
        conn.close()
        message = "Limit set successfully"

    return render_template("set_limit.html", message=message)

@app.route("/analytics")
def analytics():
    """View user activity analytics"""
    # Optional: Add password protection if you want
    password = request.args.get("pwd")
    
    if password != "admin123":  # Change this to your preferred password
        return render_template("analytics.html", activities=[], error="Invalid password")

    conn = get_db_connection()
    activities = conn.execute("""
        SELECT username, activity, timestamp, ip_address
        FROM user_activity
        ORDER BY timestamp DESC
        LIMIT 500
    """).fetchall()
    conn.close()

    return render_template("analytics.html", activities=activities)

if __name__ == "__main__":
    app.run()
