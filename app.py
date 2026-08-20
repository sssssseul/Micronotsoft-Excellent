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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS long_texts (
            id SERIAL PRIMARY KEY,
            nickname TEXT NOT NULL REFERENCES users(nickname) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS long_scores (
            id SERIAL PRIMARY KEY,
            text_id INTEGER NOT NULL REFERENCES long_texts(id) ON DELETE CASCADE,
            nickname TEXT NOT NULL,
            time_seconds NUMERIC NOT NULL,
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
        """SELECT id, cells, cpm, accuracy, played_at FROM scores
           WHERE nickname = %s ORDER BY played_at ASC""",
        (nickname,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {
            "id": r["id"],
            "cells": r["cells"],
            "cpm": r["cpm"],
            "accuracy": r["accuracy"],
            "played_at": r["played_at"].isoformat(),
        }
        for r in rows
    ]
    return jsonify(ok=True, history=result)


@app.route("/api/delete_score", methods=["POST"])
def delete_score():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    score_id = data.get("id")

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401
    if not score_id:
        return jsonify(ok=False, error="삭제할 기록을 찾을 수 없습니다."), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM scores WHERE id = %s AND nickname = %s",
        (score_id, nickname),
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True, deleted=deleted)


@app.route("/api/longtext/save", methods=["POST"])
def longtext_save():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401
    if not title or not content:
        return jsonify(ok=False, error="제목과 내용을 입력해주세요."), 400
    if len(title) > 60:
        return jsonify(ok=False, error="제목은 60자 이내로 입력해주세요."), 400
    if len(content) > 20000:
        return jsonify(ok=False, error="내용이 너무 길어요 (최대 20,000자)."), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO long_texts (nickname, title, content) VALUES (%s, %s, %s) RETURNING id",
        (nickname, title, content),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True, id=new_id)


@app.route("/api/longtext/list", methods=["POST"])
def longtext_list():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT lt.id, lt.title, LENGTH(lt.content) AS len, lt.created_at,
               COALESCE(MAX(ls.cpm), 0) AS best_cpm
        FROM long_texts lt
        LEFT JOIN long_scores ls ON ls.text_id = lt.id AND ls.nickname = lt.nickname
        WHERE lt.nickname = %s
        GROUP BY lt.id
        ORDER BY lt.created_at DESC
        """,
        (nickname,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = [
        {
            "id": r["id"],
            "title": r["title"],
            "len": r["len"],
            "best_cpm": r["best_cpm"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    return jsonify(ok=True, texts=result)


@app.route("/api/longtext/get", methods=["POST"])
def longtext_get():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    text_id = data.get("id")

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT id, title, content FROM long_texts WHERE id = %s AND nickname = %s",
        (text_id, nickname),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify(ok=False, error="글을 찾을 수 없습니다."), 404
    return jsonify(ok=True, text={"id": row["id"], "title": row["title"], "content": row["content"]})


@app.route("/api/longtext/delete", methods=["POST"])
def longtext_delete():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    text_id = data.get("id")

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM long_texts WHERE id = %s AND nickname = %s",
        (text_id, nickname),
    )
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True, deleted=deleted)


@app.route("/api/longtext/submit_score", methods=["POST"])
def longtext_submit_score():
    data = request.get_json(force=True)
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password") or ""
    text_id = data.get("text_id")
    time_seconds = float(data.get("time_seconds", 0))
    cpm = int(data.get("cpm", 0))
    accuracy = int(data.get("accuracy", 0))

    if not verify_user(nickname, password):
        return jsonify(ok=False, error="로그인 정보가 올바르지 않습니다."), 401

    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id FROM long_texts WHERE id = %s AND nickname = %s", (text_id, nickname))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify(ok=False, error="글을 찾을 수 없습니다."), 404

    cur.execute(
        "INSERT INTO long_scores (text_id, nickname, time_seconds, cpm, accuracy) VALUES (%s, %s, %s, %s, %s)",
        (text_id, nickname, time_seconds, cpm, accuracy),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(ok=True)


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
