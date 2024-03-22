import os
import base64
from collections import defaultdict

import jinja2
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

APP_URL = os.getenv("APP_URL", "https://rss.abelson.live")
if not APP_URL:
    raise Exception("APP_URL environment variable is not set")
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise Exception("DB_URL environment variable is not set")

NUM_USER_STARRED_ENTRIES = os.getenv("NUM_USER_STARRED_ENTRIES", 10)
NUM_RECENT_STARRED_ENTRIES = os.getenv("NUM_RECENT_STARRED_ENTRIES", 10)
NUM_RECENTLY_ADDED_FEEDS = os.getenv("NUM_RECENTLY_ADDED_FEEDS", 10)

# get absolute path of the template + homepage
HOMEPATE_TMPL = os.path.join(os.path.dirname(__file__), "templates/index.html.j2")
HOMEPAGE_DEST = os.path.join(os.path.dirname(__file__), "public/index.html")
ABOUT_TMPL = os.path.join(os.path.dirname(__file__), "templates/about.html.j2")
ABOUT_DEST = os.path.join(os.path.dirname(__file__), "public/about.html")

# queries
USERS_QUERY = """
with user_data as (
    select
        users.id as user_id,
        users.username as user_name,
        count(distinct feeds.id) as feeds_count,
        count(distinct entries.id) as starred_count,
        count(distinct categories.id) as category_count
    from
        users
    left join
        feeds on users.id = feeds.user_id
    left join
        entries on feeds.id = entries.feed_id and entries.starred = true
    left join
        categories on users.id = categories.user_id
    group by
        1,2
    order by
        2 asc
)
select
    * 
from
    user_data
where
    feeds_count > 0
"""

ALL_FEEDS_QUERY = """
select
    users.id as user_id,
	users.username as user_name,
    feeds.id as feed_id,
	feeds.title as feed_title,
	feeds.feed_url,
	feeds.site_url,
    categories.id as feed_category_id,
	categories.title as feed_category,
	icons.content as feed_icon,
    icons.mime_type as feed_icon_mime
from
	feeds 
left join 
	categories on feeds.category_id = categories.id
left join 
	users on feeds.user_id = users.id
left join 
	feed_icons on feeds.id = feed_icons.feed_id
left join 
	icons on feed_icons.icon_id = icons.id
order by
	users.username, categories.title, feeds.title
"""

RECENTLY_ADDED_FEEDS_QUERY = f"""
with all_feeds as (
    {ALL_FEEDS_QUERY}
)
select 
    *
from 
    all_feeds
order by
    feed_id desc
limit
    {NUM_RECENTLY_ADDED_FEEDS}
"""

STARRED_ENTRIES_QUERY = f"""
select 
    feeds.user_id as user_id,
    users.username as user_name,
    feeds.feed_url,
    feeds.title as feed_title,
    icons.content as feed_icon,
    icons.mime_type as feed_icon_mime,
    categories.id as feed_category_id,
    categories.title as feed_category,
    feeds.site_url as site_url,
    entries.author as entry_author,
    entries.title as entry_title,
    entries.url as entry_url,
    entries.published_at as entry_published_at,
    entries.changed_at as entry_changed_at
from
    entries
left join
    feeds on entries.feed_id = feeds.id
left join 
	users on feeds.user_id = users.id
left join 
    categories on feeds.category_id = categories.id
left join 
    feed_icons on feeds.id = feed_icons.feed_id
left join 
    icons on feed_icons.icon_id = icons.id
where
    entries.starred = true
order by
    entries.published_at desc
"""


RECENT_STARRED_ENTRIES_QUERY = f"""
with starred_entries as (
    {STARRED_ENTRIES_QUERY}   
)
select
    *
from
    starred_entries
order by
    entry_changed_at desc
limit 
    {NUM_RECENT_STARRED_ENTRIES}
"""

RECENT_USER_STARRED_ENTRIES_QUERY = f"""
with starred_entries as (
    {STARRED_ENTRIES_QUERY}
),

user_ranked_starred_entries as (
	select 
        *,
		row_number() over(partition by user_id order by entry_published_at desc) as starred_order
	from
		starred_entries
)
select 
    * 
from 
    user_ranked_starred_entries 
where 
    starred_order <= {NUM_USER_STARRED_ENTRIES}
"""


DEFAULT_ICON = """
data:image/png;base64,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"""

def query_db(
    query: str,
    base64_content_field: str = "feed_icon",
    base64_content_type_field: str = "feed_icon_mime",
):
    """
    Query the database and return the results as a list of dictionaries
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
                        row[base64_content_field], row[base64_content_type_field]
                    )
                data.append(row)
            return data
    finally:
        conn.close()


def binary_to_base64(binary_data, content_type):
    """
    Convert binary data to base64
    """
    if not binary_data:
        return DEFAULT_ICON
    content = base64.b64encode(binary_data.tobytes()).decode("utf-8")
    return f"data:{content_type};base64,{content}"


def get_homepage_data():
    """
    Get the data for the homepage
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


def generate_site(data):
    jinja2.Template(open(HOMEPATE_TMPL).read()).stream(data=data, app_url=APP_URL).dump(
        HOMEPAGE_DEST
    )
    jinja2.Template(open(ABOUT_TMPL).read()).stream(data=data, app_url=APP_URL).dump(
        ABOUT_DEST
    )


def main():
    print("!" * 60)
    print("Generating site...")
    print("!" * 60)
    data = get_homepage_data()
    generate_site(data)


if __name__ == "__main__":
    main()
