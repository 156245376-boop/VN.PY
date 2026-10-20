import asyncio

from aiohttp.test_utils import TestClient, TestServer

from qf.research_window import ResearchWindowView
from qf.trade_analytics import normalize_trade_filters

LEDGER = {
    "available": True,
    "trades": [
        dict(trade_id="one", status="closed", direction=1,
             first_symbol="SHFE.rb2505", last_symbol="SHFE.rb2505",
             entry_time_ns="1735780439000000000", entry_price="3301",
             exit_time_ns="1735782539000000000", exit_price="3315",
             quantity=5, initial_stop="3284", final_stop="3302",
             exit_reason="ma_reverse", gross_pnl="700", fee="30",
             net_pnl="670", fill_count=2),
    ],
    "fills": [],
}


def exercise(view):
    async def run():
        client = TestClient(TestServer(view.app()))
        await client.start_server()
        try:
            response = await client.get("/state")
            packet = await response.json()
            assert response.status == 200
            assert packet["job_id"] == "a" * 32
            assert packet["status"] == "active"
            assert packet["progress"]["percent"] == 12
            assert packet["chart_url"] == "http://127.0.0.1:45678"
            assert "password" not in packet

            response = await client.get(
                "/ledger", params={"direction": "1", "status": "closed"})
            packet = await response.json()
            assert response.status == 200
            assert [trade["trade_id"] for trade in packet["trades"]] == ["one"]
            assert packet["statistics"]["net_pnl"] == "670"
            assert "private" not in str(packet)

            response = await client.get("/ledger.csv", params={"status": "closed"})
            text = await response.text()
            assert response.status == 200
            assert "text/csv" in response.headers["Content-Type"]
            assert "trade-ledger-aaaaaaaa.csv" in response.headers["Content-Disposition"]
            assert text.startswith("\ufeff")
            assert "670" in text

            response = await client.get("/assets/not-allowed.js")
            assert response.status == 404
        finally:
            await client.close()

    asyncio.run(run())


def test_state_ledger_filters_and_csv_are_job_bound():
    view = ResearchWindowView(
        "a" * 32,
        lambda: {
            "job_id": "a" * 32, "status": "active", "running": True,
            "run_id": "20261020T000000-abcdef123456",
            "progress": {"percent": 12}, "account": {"summary": {"balance": "101000"}},
            "risk": {"quantity": 1}, "password": "private",
        },
        lambda: LEDGER,
        lambda: "http://127.0.0.1:45678",
    )
    exercise(view)


def test_chart_and_job_identity_are_validated():
    wrong_job = ResearchWindowView(
        "a" * 32, lambda: {"job_id": "b" * 32}, lambda: LEDGER,
        lambda: "http://127.0.0.1:45678")

    async def run():
        client = TestClient(TestServer(wrong_job.app()))
        await client.start_server()
        try:
            assert (await client.get("/state")).status == 503
        finally:
            await client.close()

    asyncio.run(run())

    invalid_chart = ResearchWindowView(
        "a" * 32, lambda: {"job_id": "a" * 32}, lambda: LEDGER,
        lambda: "https://example.com/chart")

    async def invalid():
        client = TestClient(TestServer(invalid_chart.app()))
        await client.start_server()
        try:
            assert (await client.get("/state")).status == 503
        finally:
            await client.close()

    asyncio.run(invalid())


def test_filter_normalization_is_shared_with_export():
    filters = normalize_trade_filters({"direction": "-1", "status": "open"})
    assert filters["direction"] == -1
    assert filters["status"] == "open"
