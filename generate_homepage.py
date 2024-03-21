
import os
import base64
from collections import defaultdict

import boto3
import jinja2
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise Exception("DB_URL environment variable is not set")

DO_REGION = os.getenv("DO_REGION", "nyc3")
DO_ENDPOINT = os.getenv("DO_ENDPOINT", "https://nyc3.digitaloceanspaces.com")
DO_SPACE = os.getenv("DO_SPACE", "feederss")
DO_ACCESS_KEY = os.getenv("DO_ACCESS_KEY")
DO_SECRET_KEY = os.getenv("DO_SECRET_KEY")
if not DO_ACCESS_KEY or not DO_SECRET_KEY:
    raise Exception("DO_ACCESS_KEY or DO_SECRET_KEY environment variable is not set")

FEED_QUERY = """
select
    users.id as user_id,
	users.username as user_name,
	feeds.title as feed_title,
	feeds.feed_url,
	feeds.site_url,
	categories.title as feed_category,
	icons.content as feed_icon_content,
    icons.mime_type as feed_icon_mime_type
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

RECENT_STARRED_ENTIRES_QUERY = """
with starred_entries as (
	select 
		feeds.user_id as user_id,
	    feeds.feed_url,
		feeds.title as feed_title,
		icons.content as feed_icon_content,
		icons.mime_type as feed_icon_mime_type,
	    categories.title as feed_category,
		feeds.site_url as site_url,
        entries.author as entry_author,
		entries.title as entry_title,
		entries.url as entry_url,
		entries.published_at as entry_published_at,
		row_number() over(partition by feeds.user_id order by entries.published_at desc) as starred_order
	from
		entries
	left join
		feeds on entries.feed_id = feeds.id
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

)
select 
    * 
from 
    starred_entries 
where 
starred_order <= 5
"""
# get absolute path of the template + homepage
TEMPLATE = os.path.join(os.path.dirname(__file__), "index.html.j2")
HOMEPAGE = os.path.join(os.path.dirname(__file__), "public/index.html")

def upload_file_to_do_space(local_path, remote_path="index.html", content_type="text/html"):
    """
    Upload a file to DigitalOcean Spaces using boto3
    """
    s3 = boto3.client('s3',
                      region_name=DO_REGION,
                      endpoint_url=DO_ENDPOINT,
                      aws_access_key_id=DO_ACCESS_KEY,
                      aws_secret_access_key=DO_SECRET_KEY)
    # upload file and set acl to public-read
    s3.upload_file(local_path, DO_SPACE, remote_path, ExtraArgs={'ACL': 'public-read', 'ContentType': content_type})

def query_db(query: str):
    """
    Query the database and return the results as a list of dictionaries
    """
    # Connect to the database
    conn = psycopg2.connect(DB_URL)
    conn.set_client_encoding('UTF-8')
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def binary_to_base64(binary_data):
    """
    Convert binary data to base64
    """
    return base64.b64encode(binary_data.tobytes()).decode("utf-8")


def datetime_to_string(datetime):
    """
    Convert a datetime object to a string
    """
    return datetime.strftime(r"%m/%d/%Y")


def get_homepage_data():
    """
    Get the data for the homepage
    """
    # Get the feeds
    feeds = query_db(FEED_QUERY)
    userdict = defaultdict(lambda: {"name": None, "feeds": defaultdict(list), "starred_entries": []})

    for f in feeds:
        userdict[f["user_id"]]['name'] = f['user_name']
        # Convert the icon to base64
        if f["feed_icon_content"]:
            f["feed_icon_content"] = binary_to_base64(f["feed_icon_content"])
        userdict[f["user_id"]]["feeds"][f["feed_category"]].append(f)

    # Get the recent starred entries
    recent_starred_entries = query_db(RECENT_STARRED_ENTIRES_QUERY)
    for e in recent_starred_entries:
        e["entry_title"] = e["entry_title"]
        # Convert the icon to base64
        if e["feed_icon_content"]:
            e["feed_icon_content"] = binary_to_base64(e["feed_icon_content"])
        # Convert the datetime to a string
        e["entry_published_at"] = datetime_to_string(e["entry_published_at"])
        userdict[e["user_id"]]["starred_entries"].append(e)
    return userdict

def generate_homepage(data):
    jinja2.Template(open(TEMPLATE).read()).stream(users=data).dump(HOMEPAGE)
    return HOMEPAGE

def upload_homepage(local_path):
    upload_file_to_do_space(local_path, "index.html")
    

def main():
    print("!"*60)
    print("Generating homepage...")
    print("!"*60)
    data = get_homepage_data()
    local_path = generate_homepage(data)
    upload_file_to_do_space(local_path)

if __name__ == "__main__":
    main()

