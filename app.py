import os
from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder=".")

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    if not DATABASE_URL:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nickname TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scores (
            id SERIAL PRIMARY KEY,
            nickname TEXT NOT NULL REFERENCES users(nickname) ON DELETE CASCADE,
            cells INTEGER NOT NULL,
            cpm INTEGER NOT NULL,
            accuracy INTEGER NOT NULL,
            played_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


def verify_user(nickname, password):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE nickname = %s", (nickname,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user is None:
        return False
    return check_password_hash(user["password_hash"], password)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""

    if not nickname or not password:
        return jsonify(ok=False, error="닉네임과 비밀번호를 입력해주세요."), 400
    if len(nickname) > 20:
        return jsonify(ok=False, error="닉네임은 20자 이내로 입력해주세요."), 400
    if len(password) < 4:
        return jsonify(ok=False, error="비밀번호는 4자 이상으로 입력해주세요."), 400

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE nickname = %s", (nickname,))
    user = cur.fetchone()

    if user is None:
        pw_hash = generate_password_hash(password)
        cur.execute(
            "INSERT INTO users (nickname, password_hash) VALUES (%s, %s)",
            (nickname, pw_hash),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(ok=True, isNew=True, nickname=nickname)

    ok = check_password_hash(user["password_hash"], password)
    cur.close()
    conn.close()
    if not ok:
        return jsonify(ok=False, error="비밀번호가 일치하지 않습니다."), 401
    return jsonify(ok=True, isNew=False, nickname=nickname)


@app.route("/api/save_score", methods=["POST"])
def save_score():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    cells = int(data.get("cells", 0))
    cpm = int(data.get("cpm", 0))
    accuracy = int(data.get("accuracy", 0))

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scores (nickname, cells, cpm, accuracy) VALUES (%s, %s, %s, %s)",
        (nickname, cells, cpm, accuracy),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route("/api/history", methods=["POST"])
def history():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """SELECT cells, cpm, accuracy, played_at FROM scores
           WHERE nickname = %s ORDER BY played_at ASC""",
        (nickname,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {
            "cells": r["cells"],
            "cpm": r["cpm"],
            "accuracy": r["accuracy"],
            "played_at": r["played_at"].isoformat(),
        }
        for r in rows
    ]
    return jsonify(ok=True, history=result)


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT nickname, cpm, cells FROM (
            SELECT DISTINCT ON (nickname) nickname, cpm, cells
            FROM scores
            ORDER BY nickname, cpm DESC
        ) best
        ORDER BY cpm DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {"rank": i + 1, "nickname": r["nickname"], "cpm": r["cpm"], "cells": r["cells"]}
        for i, r in enumerate(rows)
    ]
    return jsonify(ok=True, leaderboard=result)


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
