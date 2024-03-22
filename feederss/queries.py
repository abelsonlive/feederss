from .settings import (
    NUM_RECENTLY_ADDED_FEEDS,
    NUM_RECENT_STARRED_ENTRIES,
    NUM_USER_STARRED_ENTRIES,
)

# queries
USERS_QUERY = f"""--sql
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


ALL_FEEDS_QUERY = f"""--sql
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

RECENTLY_ADDED_FEEDS_QUERY = f"""--sql
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

STARRED_ENTRIES_QUERY = f"""--sql
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


RECENT_STARRED_ENTRIES_QUERY = f"""--sql
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

RECENT_USER_STARRED_ENTRIES_QUERY = f"""--sql
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
