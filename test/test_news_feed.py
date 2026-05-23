import json

import pytest
from pydantic import ValidationError

from agents.news_feed import NewsFeed, NewsItem, Scenario


def test_news_item_accepts_only_raw_news_fields():
    item = NewsItem(
        id="news-001",
        headline="Apple reports stronger than expected quarterly revenue",
        body="Apple announced quarterly revenue above analyst expectations.",
    )

    assert item.id == "news-001"
    assert item.headline.startswith("Apple reports")


@pytest.mark.parametrize("field", ["token", "sentiment", "impact"])
def test_news_item_rejects_interpretation_fields(field):
    payload = {
        "id": "news-001",
        "headline": "Apple reports stronger than expected quarterly revenue",
        "body": "Apple announced quarterly revenue above analyst expectations.",
        field: "not allowed",
    }

    with pytest.raises(ValidationError):
        NewsItem.model_validate(payload)


def test_load_news_rejects_interpretation_fields(tmp_path):
    path = tmp_path / "news.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "news-001",
                    "headline": "Apple reports stronger than expected quarterly revenue",
                    "body": "Apple announced quarterly revenue above analyst expectations.",
                    "token": "AAPL",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        NewsFeed.load_news(path)


def test_same_seed_produces_same_schedule():
    news = [
        NewsItem(id="news-001", headline="First headline", body="First body"),
        NewsItem(id="news-002", headline="Second headline", body="Second body"),
        NewsItem(id="news-003", headline="Third headline", body="Third body"),
    ]
    scenario = Scenario(
        seed=438,
        news_file="data/news.json",
        policy_address="0xpolicy",
        min_interval_ticks=2,
        max_interval_ticks=5,
        max_events=3,
        broadcast_to_all_traders=True,
        tokens=[
            {"symbol": "USD", "address": "0xusd"},
            {"symbol": "AAPL", "address": "0xaapl"},
        ],
        pools=[
            {
                "id": "AAPL-USD",
                "base_symbol": "AAPL",
                "quote_symbol": "USD",
                "pool_address": "0xpool",
                "lp_token_address": "0xlp",
                "vault_address": "0xvault",
            }
        ],
    )

    first = NewsFeed(news, scenario).schedule()
    second = NewsFeed(news, scenario).schedule()

    assert first == second
    assert len(first) == 3
    assert [event.tick for event in first] == sorted(event.tick for event in first)


def test_broadcast_delivers_same_news_to_all_traders_at_tick():
    news = [
        NewsItem(id="news-001", headline="First headline", body="First body"),
        NewsItem(id="news-002", headline="Second headline", body="Second body"),
    ]
    scenario = Scenario(
        seed=438,
        news_file="data/news.json",
        policy_address="0xpolicy",
        min_interval_ticks=1,
        max_interval_ticks=1,
        max_events=1,
        broadcast_to_all_traders=True,
        tokens=[
            {"symbol": "USD", "address": "0xusd"},
            {"symbol": "NVDA", "address": "0xnvda"},
        ],
        pools=[
            {
                "id": "NVDA-USD",
                "base_symbol": "NVDA",
                "quote_symbol": "USD",
                "pool_address": "0xpool",
                "lp_token_address": "0xlp",
                "vault_address": "0xvault",
            }
        ],
    )
    feed = NewsFeed(news, scenario)
    event = feed.schedule()[0]

    delivered = feed.broadcast_at(event.tick, trader_ids=["trader-0", "trader-1", "trader-2"])

    assert set(delivered) == {"trader-0", "trader-1", "trader-2"}
    assert {item.id for item in delivered.values()} == {event.news.id}

