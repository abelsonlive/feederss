import os
import argparse
import base64
import json
import signal
import sys
import time
import traceback
from datetime import datetime
from collections import defaultdict

import jinja2
import psycopg2
import psycopg2.extras

from .settings import (
    APP_URL,
    CHAT_URL,
    DB_URL,
    DEFAULT_ICON,
    HEARTBEAT_FILE,
    PUBLIC_DIR,
    REFRESH_INTERVAL_SECONDS,
)
from .queries import (
    USERS_QUERY,
    ALL_FEEDS_QUERY,
    RECENTLY_ADDED_FEEDS_QUERY,
    RECENT_STARRED_ENTRIES_QUERY,
    RECENT_USER_STARRED_ENTRIES_QUERY,
)

# get absolute path of the template + homepage
HOMEPAGE_TMPL = os.path.join(os.path.dirname(__file__), "./templates/index.html.j2")
HOMEPAGE_DEST = os.path.join(PUBLIC_DIR, "index.html")
ABOUT_TMPL = os.path.join(os.path.dirname(__file__), "./templates/about.html.j2")
ABOUT_DEST = os.path.join(PUBLIC_DIR, "about.html")
DATA_DEST = os.path.join(PUBLIC_DIR, "data.json")


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
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    vars = {
        "data": data,
        "app_url": APP_URL,
        "chat_url": CHAT_URL,
    }
    jinja2.Template(open(HOMEPAGE_TMPL).read()).stream(**vars).dump(HOMEPAGE_DEST)
    jinja2.Template(open(ABOUT_TMPL).read()).stream(**vars).dump(ABOUT_DEST)
    with open(DATA_DEST, "w") as f:
        json.dump(data, f, indent=2, default=str)


def build():
    """
    Query the database and render the site into PUBLIC_DIR
    """
    print("🍦" * 24)
    print(
        f"😋 Generating feederss [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]  😋"
    )
    print("🍦" * 24)
    generate_site(get_site_data())
    print(f"📁 wrote site to {PUBLIC_DIR}")


def build_and_publish():
    """
    Render the site and sync it to object storage
    """
    # imported lazily so `build` keeps working without boto3 installed
    from .publish import publish

    build()
    publish()


def touch_heartbeat():
    """
    Record a successful run for the container healthcheck to read
    """
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(int(time.time())))
    except OSError as e:
        # a heartbeat we can't write is not worth failing a good run over
        print(f"⚠️  could not write heartbeat to {HEARTBEAT_FILE}: {e}")


def loop():
    """
    Build and publish on a fixed interval until asked to stop.

    Deliberately a sleep loop rather than cron: cron in a container needs the
    environment exported into a crontab by hand (it does not inherit the
    container's env), logs somewhere other than stdout, and gives docker no
    way to distinguish "sleeping" from "wedged". This gives all three for
    free, at the cost of drift between runs that does not matter here.
    """
    stopping = {"now": False}

    def handle_signal(signum, _frame):
        print(f"👋 got signal {signum}, finishing up")
        stopping["now"] = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print(f"🔁 refreshing every {REFRESH_INTERVAL_SECONDS}s")
    while not stopping["now"]:
        try:
            build_and_publish()
            touch_heartbeat()
        except Exception:
            # one bad run (miniflux's postgres restarting, a Spaces blip)
            # should not take the daemon down — log it and try again next tick
            traceback.print_exc()
            print("💥 refresh failed, retrying next interval")

        # sleep in short slices so a SIGTERM doesn't wait out the interval
        deadline = time.monotonic() + REFRESH_INTERVAL_SECONDS
        while not stopping["now"] and time.monotonic() < deadline:
            time.sleep(min(5, deadline - time.monotonic()))

    print("🛑 stopped")


def healthcheck():
    """
    Exit non-zero if the last successful run is older than one interval
    (plus a grace period for the run itself)
    """
    grace = REFRESH_INTERVAL_SECONDS * 2
    try:
        age = time.time() - os.path.getmtime(HEARTBEAT_FILE)
    except OSError:
        print(f"no heartbeat at {HEARTBEAT_FILE} yet")
        return 1
    if age > grace:
        print(f"last successful refresh was {int(age)}s ago (limit {grace}s)")
        return 1
    print(f"last successful refresh was {int(age)}s ago")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="feederss")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("build", help="render the site into PUBLIC_DIR")
    subparsers.add_parser("publish", help="render the site and sync it to S3")
    subparsers.add_parser("loop", help="publish every REFRESH_INTERVAL_SECONDS")
    subparsers.add_parser("healthcheck", help="check the daemon's last run")
    args = parser.parse_args()

    # bare `python -m feederss` stays what it always was: a local build
    commands = {
        None: build,
        "build": build,
        "publish": build_and_publish,
        "loop": loop,
        "healthcheck": healthcheck,
    }
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
