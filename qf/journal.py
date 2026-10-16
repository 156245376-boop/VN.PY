import csv
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


class PaperLock:
    """内核文件锁在进程退出时释放；锁文件不删除，避免删锁竞争。"""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "paper.lock"
        self.file = None

    def __enter__(self):
        self.file = self.path.open("a+b")
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise ValueError("已有模拟进程持有账户锁") from None
        return self

    def __exit__(self, *_):
        self.file.close()


class Journal:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path / "journal.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS signals (minute INTEGER PRIMARY KEY, target INTEGER,
                                                applied INTEGER DEFAULT 0, input TEXT);
            CREATE TABLE IF NOT EXISTS fills (key TEXT PRIMARY KEY, order_id TEXT, symbol TEXT,
                direction TEXT, offset TEXT, volume INTEGER, price REAL, time_ns INTEGER);
            CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, symbol TEXT, direction TEXT,
                offset TEXT, volume INTEGER);
            CREATE TABLE IF NOT EXISTS equity (time_ns INTEGER PRIMARY KEY, balance REAL,
                                               commission REAL);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT, code TEXT);
        """)

    @classmethod
    def create(cls, root, mode, config, metadata=None):
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
        path = root / run_id
        path.mkdir(parents=True)
        journal = cls(path)
        journal.set("config", config)
        journal.set("mode", mode)
        payload = dict(metadata or {}, run_id=run_id, mode=mode, config=config)
        (path / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        return journal

    @classmethod
    def resume(cls, path, config):
        if not (path / "journal.sqlite3").is_file():
            raise ValueError("实验记录不存在")
        journal = cls(path)
        if journal.get("mode") != "paper" or journal.get("config") != config:
            journal.close()
            raise ValueError("恢复模式或配置不匹配")
        return journal

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, json.dumps(value)))

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def signal(self, minute, target, inputs=None):
        with self.db:
            last = self.db.execute("SELECT max(minute) FROM signals").fetchone()[0]
            if last is not None and minute <= last:
                return False
            self.db.execute("INSERT INTO signals(minute,target,input) VALUES (?,?,?)",
                            (minute, target, json.dumps(inputs)))
        return True

    def applied(self, minute):
        with self.db:
            self.db.execute("UPDATE signals SET applied=1 WHERE minute=?", (minute,))

    def fill(self, fill):
        fields = ("key", "order_id", "symbol", "direction", "offset", "volume", "price", "time_ns")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO fills VALUES (?,?,?,?,?,?,?,?)",
                            tuple(fill[k] for k in fields))

    def order(self, order_id, symbol, direction, offset, volume):
        with self.db:
            self.db.execute("INSERT INTO orders VALUES (?,?,?,?,?)",
                            (order_id, symbol, direction, offset, volume))

    def owned(self):
        return {r[0] for r in self.db.execute("SELECT id FROM orders")}

    def expected_position(self):
        return self.db.execute("SELECT coalesce(sum(CASE WHEN direction='BUY' THEN volume "
                               "ELSE -volume END),0) FROM fills").fetchone()[0]

    def equity(self, time_ns, balance, commission):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?)",
                            (time_ns, balance, commission))

    def event(self, code):
        with self.db:
            self.db.execute("INSERT INTO events(time,code) VALUES (?,?)",
                            (datetime.now(UTC).isoformat(), code))

    def export(self):
        for table in ("signals", "fills", "orders", "equity", "events"):
            cursor = self.db.execute(f"SELECT * FROM {table}")
            with (self.path / f"{table}.csv").open("w", newline="", encoding="utf-8-sig") as out:
                writer = csv.writer(out)
                writer.writerow([d[0] for d in cursor.description])
                writer.writerows(cursor)
        row = self.db.execute("SELECT balance,commission FROM equity ORDER BY time_ns DESC "
                              "LIMIT 1").fetchone()
        summary = self.get("sdk_statistics")
        if summary:
            value = (f"期末权益 {summary['end_balance']:.2f}；"
                     + f"全区间 SDK 模拟费用 {summary['commission']:.2f}。\n")
            initial = self.get("config").get("initial_balance", 100000)
            value += (f"相对初始权益净收益 {summary['end_balance'] - initial:.2f}；"
                      + f"收益率 {summary['end_balance'] / initial - 1:.4%}。\n")
        else:
            value = (f"末次账户权益 {row[0]:.2f}；当交易日费用 {row[1]:.2f}。\n"
                     if row else "尚无权益记录。\n")
        text = ("# 实验记录\n\n" + value + "\n\n"
                + "回测基准目录 comparison.json / comparison.md 保存独立双倍费用回放比较。\n"
                + "本地回测为 SDK 简化撮合（不部分成交、分钟盘口可能合成），费用与保证金"
                + "为 SDK 每手模型，非历史真实成本。浮动持仓按市值计入权益，结束不自动平仓。\n\n"
                + f"状态：{self.get('status', 'created')}；原因：{self.get('reason', 'none')}。\n"
                + "模拟收益不证明策略有效；账户连接和权限以实际联网验收为准。\n")
        (self.path / "report.md").write_text(text, encoding="utf-8")

    def close(self):
        self.db.close()
