import os
import base64
import json
from datetime import datetime
from collections import defaultdict

import jinja2
import psycopg2
import psycopg2.extras

from .settings import APP_URL, CHAT_URL, DB_URL, DEFAULT_ICON
from .queries import (
    USERS_QUERY,
    ALL_FEEDS_QUERY,
    RECENTLY_ADDED_FEEDS_QUERY,
    RECENT_STARRED_ENTRIES_QUERY,
    RECENT_USER_STARRED_ENTRIES_QUERY,
)

# get absolute path of the template + homepage
HOMEPAGE_TMPL = os.path.join(os.path.dirname(__file__), "./templates/index.html.j2")
HOMEPAGE_DEST = os.path.join(os.path.dirname(__file__), "../public/index.html")
ABOUT_TMPL = os.path.join(os.path.dirname(__file__), "./templates/about.html.j2")
ABOUT_DEST = os.path.join(os.path.dirname(__file__), "../public/about.html")
DATA_DEST = os.path.join(os.path.dirname(__file__), "../public/data.json")


def binary_to_base64(binary_data, content_type: str):
    """
    Convert binary data to base64 with the specified content type
    """
    if not binary_data:
        return DEFAULT_ICON
    content = base64.b64encode(binary_data.tobytes()).decode("utf-8")
    return f"data:{content_type};base64,{content}"


def query_db(
    query: str,
    base64_content_field: str = "feed_icon",
    base64_content_type_field: str = "feed_icon_mime",
):
    """
    Query the database, convert binary images to base64,
    and return the results as a list of dictionaries
    """
    # Connect to the database
    conn = psycopg2.connect(DB_URL)
    conn.set_client_encoding("UTF-8")
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            data = []
            for row in cur.fetchall():
                if base64_content_field in row:
                    row[base64_content_field] = binary_to_base64(
                        row[base64_content_field],
                        row[base64_content_type_field],
                    )
                data.append(row)
            return data
    finally:
        conn.close()


def get_site_data():
    """
    Get the data for the site via queries
    """
    # Output data structure.
    data = {
        "new_feeds": [],
        "new_stars": [],
        "users": [],
        "user_data": defaultdict(
            lambda: {
                "name": None,
                "feed_categories": defaultdict(lambda: {"id": None, "feeds": []}),
                "stars": [],
            }
        ),
    }
    # Get users
    data["users"] = query_db(USERS_QUERY)

    # Get the recently starred entries
    data["new_stars"] = query_db(RECENT_STARRED_ENTRIES_QUERY)

    # Get the recently added feeds
    data["new_feeds"] = query_db(RECENTLY_ADDED_FEEDS_QUERY)

    # get user feeds
    all_feeds = query_db(ALL_FEEDS_QUERY)
    for f in all_feeds:
        # set the user name
        data["user_data"][f["user_id"]]["name"] = f["user_name"]
        # add the feed to the user's feeds
        data["user_data"][f["user_id"]]["feed_categories"][f["feed_category"]]["id"] = (
            f["feed_category_id"]
        )
        data["user_data"][f["user_id"]]["feed_categories"][f["feed_category"]][
            "feeds"
        ].append(f)

    # Get user's recently starred entries
    recent_starred_entries = query_db(RECENT_USER_STARRED_ENTRIES_QUERY)
    for e in recent_starred_entries:
        # add the starred entry to the user's starred entries
        data["user_data"][e["user_id"]]["stars"].append(e)

    return data


def generate_site(data: dict):
    """
    Generate the site using the data
    """
    vars = {
        "data": data,
        "app_url": APP_URL,
        "chat_url": CHAT_URL,
    }
    jinja2.Template(open(HOMEPAGE_TMPL).read()).stream(**vars).dump(HOMEPAGE_DEST)
    jinja2.Template(open(ABOUT_TMPL).read()).stream(**vars).dump(ABOUT_DEST)
    with open(DATA_DEST, "w") as f:
        json.dump(data, f, indent=2, default=str)


def main():
    print("🍦" * 24)
    print(
        f"😋 Generating feederss [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  😋"
    )
    print("🍦" * 24)
    generate_site(get_site_data())


if __name__ == "__main__":
    main()
