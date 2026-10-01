"""Pagination is normalized from the native headers only."""

from __future__ import annotations

from conftest import _Headers
from runtime.pagination import pagination_from_headers, parse_link_header


def _headers(**values: str) -> _Headers:
    return _Headers(values)


def test_native_headers_are_normalized() -> None:
    result = pagination_from_headers(
        _headers(
            **{
                "X-WP-Total": "137",
                "X-WP-TotalPages": "7",
                "Link": (
                    '<https://shop.example/wp-json/wp/v2/posts?page=1>; rel="prev", '
                    '<https://shop.example/wp-json/wp/v2/posts?page=3>; rel="next"'
                ),
            }
        ),
        page=2,
        per_page=20,
    )
    assert result == {
        "total": 137,
        "total_pages": 7,
        "page": 2,
        "per_page": 20,
        "next_link": "https://shop.example/wp-json/wp/v2/posts?page=3",
        "previous_link": "https://shop.example/wp-json/wp/v2/posts?page=1",
        "has_more": True,
    }


def test_absent_headers_yield_nulls_rather_than_invented_numbers() -> None:
    result = pagination_from_headers(_headers(), page=None, per_page=None)
    assert result == {
        "total": None,
        "total_pages": None,
        "page": None,
        "per_page": None,
        "next_link": None,
        "previous_link": None,
        "has_more": False,
    }


def test_the_last_page_reports_no_more() -> None:
    result = pagination_from_headers(
        _headers(**{"X-WP-Total": "5", "X-WP-TotalPages": "2"}), page=2, per_page=3
    )
    assert result["has_more"] is False


def test_has_more_falls_back_to_the_link_header() -> None:
    result = pagination_from_headers(
        _headers(Link='<https://shop.example/wp-json/wc/v3/orders?page=2>; rel="next"'),
        page=None,
        per_page=None,
    )
    assert result["has_more"] is True
    assert result["next_link"].endswith("page=2")


def test_malformed_counts_are_dropped_rather_than_guessed() -> None:
    result = pagination_from_headers(
        _headers(**{"X-WP-Total": "many", "X-WP-TotalPages": "-3"}), page=1, per_page=10
    )
    assert result["total"] is None
    assert result["total_pages"] is None


def test_link_parsing_is_bounded_and_scheme_restricted() -> None:
    assert parse_link_header("") == {}
    assert parse_link_header('<javascript:alert(1)>; rel="next"') == {}
    assert parse_link_header("<" + "x" * 3000 + '>; rel="next"') == {}
    assert parse_link_header(
        '<https://a.example/1>; rel="next", <https://b.example/2>; rel="next"'
    ) == {"next": "https://a.example/1"}
    oversized = ", ".join(f'<https://a.example/{index}>; rel="next"' for index in range(500))
    assert parse_link_header(oversized) == {}


def test_a_headerless_response_object_is_tolerated() -> None:
    assert pagination_from_headers(None)["total"] is None
    assert pagination_from_headers({"X-WP-Total": "3"})["total"] == 3
