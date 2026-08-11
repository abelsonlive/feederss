feederss
=========

A sidekick for [miniflux](https://miniflux.app/), an open-source RSS reader, which promotes social RSS.

see it in action: https://feederss.abelson.live

feederss reads a miniflux database directly and renders a small static site —
who subscribes to what, which categories they keep, and what's been starred
recently — then syncs that site to S3-compatible object storage.

It runs as a sidecar container next to miniflux, refreshing on an interval.

## how it works

```
miniflux-postgres ──► feederss ──► DigitalOcean Spaces ──► feederss.abelson.live
                     (every hour)      (bucket: feederss)
```

1. `build` queries the miniflux database and renders `public/index.html`,
   `public/about.html` and `public/data.json` from the templates in
   `feederss/templates/`.
2. `publish` does the same, then syncs everything under `public/` to the
   bucket — uploading only files whose MD5 differs from the object's ETag,
   and deleting objects that no longer exist locally.
3. `loop` repeats step 2 every `REFRESH_INTERVAL_SECONDS`. This is what the
   container runs.

## configuration

Everything is environment variables, read from the real environment or from a
`.env` file in the working directory.

### required

| variable | what it is |
| --- | --- |
| `DB_URL` | Postgres connection string for the **miniflux** database |
| `APP_URL` | URL of your miniflux instance, linked from the site header |
| `CHAT_URL` | URL the header's chat icon points at |

### required to publish

Not needed for `build`.

| variable | default | what it is |
| --- | --- | --- |
| `S3_ACCESS_KEY_ID` | — | Spaces access key |
| `S3_SECRET_ACCESS_KEY` | — | Spaces secret key |
| `S3_BUCKET` | `feederss` | bucket to publish into |
| `S3_REGION` | `nyc3` | region |
| `S3_ENDPOINT_URL` | `https://$S3_REGION.digitaloceanspaces.com` | any S3-compatible endpoint |

### optional

| variable | default | what it is |
| --- | --- | --- |
| `REFRESH_INTERVAL_SECONDS` | `3600` | how long `loop` sleeps between runs |
| `PUBLIC_DIR` | `./public` | where the site is rendered |
| `S3_PREFIX` | *(none)* | publish under a key prefix instead of the bucket root |
| `S3_ACL` | `public-read` | canned ACL for uploaded objects |
| `S3_DELETE_ORPHANS` | `true` | delete bucket objects the generator no longer produces |
| `S3_HTML_CACHE_CONTROL` | `public, max-age=300` | `Cache-Control` for `.html`/`.json` |
| `S3_ASSET_CACHE_CONTROL` | `public, max-age=3600` | `Cache-Control` for css/js/images |
| `HEARTBEAT_FILE` | `/tmp/feederss-heartbeat` | touched after each successful run, read by the healthcheck |
| `NUM_USER_STARRED_ENTRIES` | `10` | starred entries shown per user |
| `NUM_RECENT_STARRED_ENTRIES` | `20` | entries in the "recently starred" list |
| `NUM_RECENTLY_ADDED_FEEDS` | `20` | feeds in the "recently added" list |

## local development

```bash
make install          # pip install -r requirements.txt
cp .env.example .env  # then fill it in
make build            # render the site into public/
make start            # serve public/ at http://localhost:3030
make watch            # rebuild whenever feederss/ changes (needs entr)
make publish          # render AND sync to object storage
```

`make build` needs to reach the miniflux database. Miniflux's Postgres isn't
published outside its Docker network, so from a laptop that means tunneling to
it first:

```bash
ssh -L 5432:localhost:5432 the-gibson   # or wherever miniflux runs
# then in .env:
# DB_URL=postgres://<user>:<password>@localhost:5432/<db>?sslmode=disable
```

## docker

```bash
make docker-build                     # build the image
make docker-run                       # run it against your .env
```

The image runs `python -m feederss loop` as a non-root user and ships a
`HEALTHCHECK` that fails once the last successful refresh is older than two
intervals — so a wedged refresh surfaces as an unhealthy container rather than
a site that quietly stops updating.

A cron daemon would have been the other option; the sleep loop is deliberate.
cron in a container doesn't inherit the container's environment (you'd have to
export it into a crontab by hand), it logs somewhere other than stdout, and it
gives docker nothing to healthcheck against.

Each subcommand is also runnable directly:

```bash
docker run --rm --env-file .env registry.gitlab.com/abelsonlive/feederss python -m feederss publish
```

## deployment

CI (`.gitlab-ci.yml`) builds the image on every push and, on the default
branch, pushes it to this project's container registry as both
`registry.gitlab.com/abelsonlive/feederss:<short-sha>` and `:latest`. No
secrets to configure — it authenticates with the built-in job token. The
project is public, so the images pull anonymously.

The container is deployed as a sidecar inside miniflux's compose project in
[home.abelson.live](https://github.com/abelsonlive/home.abelson.live):
`compose/miniflux/docker-compose.yml.j2`, configured by
`ansible/roles/miniflux/defaults/main.yml`, with the Spaces credentials in
`vault_feederss`.

To ship a change: merge to `main` here, let CI push the image, then in
home.abelson.live run

```bash
make update HOST=the-gibson SERVICE=miniflux
```

The deploy tracks `:latest` and force-pulls, so there's no tag to bump. To
roll back, pin the previous short SHA in
`ansible/roles/miniflux/defaults/main.yml` (`feederss_version`) and re-run
that command — every CI run pushes a SHA tag alongside `latest` for exactly
this.
