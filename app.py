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
    # TEMP: reset broken tables from an earlier failed deploy attempt.
    # Remove this line after the next successful deploy.
    cur.execute("DROP TABLE IF EXISTS matches, scores, users CASCADE;")
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            player1_nickname TEXT NOT NULL,
            player1_cells INTEGER,
            player1_cpm INTEGER,
            player1_accuracy INTEGER,
            player2_nickname TEXT,
            player2_cells INTEGER,
            player2_cpm INTEGER,
            player2_accuracy INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
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


import random
import string


def gen_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@app.route("/api/match/create", methods=["POST"])
def match_create():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor()
    code = gen_code()
    for _ in range(6):
        try:
            cur.execute(
                "INSERT INTO matches (code, player1_nickname) VALUES (%s, %s)",
                (code, nickname),
            )
            conn.commit()
            break
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            code = gen_code()
    cur.close()
    conn.close()
    return jsonify(ok=True, code=code)


@app.route("/api/match/join", methods=["POST"])
def match_join():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip().upper()
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM matches WHERE code = %s", (code,))
    m = cur.fetchone()
    if not m:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="존재하지 않는 코드예요."), 404
    if m["player1_nickname"] == nickname:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="자기 자신과는 대결할 수 없어요."), 400
    if m["player2_nickname"] and m["player2_nickname"] != nickname:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="이미 인원이 찬 대결이에요."), 400

    if not m["player2_nickname"]:
        cur.execute(
            "UPDATE matches SET player2_nickname = %s WHERE code = %s",
            (nickname, code),
        )
        conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True, opponent=m["player1_nickname"])


@app.route("/api/match/submit", methods=["POST"])
def match_submit():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip().upper()
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    cells = int(data.get("cells", 0))
    cpm = int(data.get("cpm", 0))
    accuracy = int(data.get("accuracy", 0))

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM matches WHERE code = %s", (code,))
    m = cur.fetchone()
    if not m:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="존재하지 않는 코드예요."), 404

    if m["player1_nickname"] == nickname:
        cur.execute(
            "UPDATE matches SET player1_cells=%s, player1_cpm=%s, player1_accuracy=%s WHERE code=%s",
            (cells, cpm, accuracy, code),
        )
    elif m["player2_nickname"] == nickname:
        cur.execute(
            "UPDATE matches SET player2_cells=%s, player2_cpm=%s, player2_accuracy=%s WHERE code=%s",
            (cells, cpm, accuracy, code),
        )
    else:
        cur.close()
        conn.close()
        return jsonify(ok=False, error="이 대결에 참가하지 않았습니다."), 400

    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


@app.route("/api/match/status", methods=["POST"])
def match_status():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip().upper()

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM matches WHERE code = %s", (code,))
    m = cur.fetchone()
    cur.close()
    conn.close()
    if not m:
        return jsonify(ok=False, error="존재하지 않는 코드예요."), 404

    return jsonify(
        ok=True,
        match={
            "code": m["code"],
            "player1": m["player1_nickname"],
            "player1_cells": m["player1_cells"],
            "player1_cpm": m["player1_cpm"],
            "player1_accuracy": m["player1_accuracy"],
            "player2": m["player2_nickname"],
            "player2_cells": m["player2_cells"],
            "player2_cpm": m["player2_cpm"],
            "player2_accuracy": m["player2_accuracy"],
        },
    )


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
