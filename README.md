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
miniflux's postgres ──► feederss ──► object storage ──► your static site
                       (every hour)
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
`.env` file in the working directory. Start from `.env.example`.

### required

| variable | what it is |
| --- | --- |
| `DB_URL` | Postgres connection string for the **miniflux** database |
| `APP_URL` | URL of your miniflux instance, linked from the site header |

### required to publish

Not needed for `build`.

| variable | default | what it is |
| --- | --- | --- |
| `S3_BUCKET` | — | bucket to publish into |
| `S3_ACCESS_KEY_ID` | — | access key |
| `S3_SECRET_ACCESS_KEY` | — | secret key |
| `S3_ENDPOINT_URL` | *(AWS S3)* | set for any S3-compatible provider — DigitalOcean Spaces, Cloudflare R2, MinIO, … |
| `S3_REGION` | `us-east-1` | region, where the provider uses one |

### optional

| variable | default | what it is |
| --- | --- | --- |
| `CHAT_URL` | *(none)* | chat link in the site header; omit it and the link isn't rendered |
| `REFRESH_INTERVAL_SECONDS` | `3600` | how long `loop` sleeps between runs |
| `PUBLIC_DIR` | `./public` | where the site is rendered |
| `S3_PREFIX` | *(none)* | publish under a key prefix instead of the bucket root |
| `S3_ACL` | *(none)* | canned ACL for uploaded objects. Left unset, no ACL is sent, which is what modern S3 buckets require (ACLs are disabled by default there, and public access comes from a bucket policy). Set `public-read` for providers that still expect per-object ACLs, like DigitalOcean Spaces |
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

`make build` needs to reach the miniflux database. Miniflux's Postgres usually
isn't published outside its Docker network, so from a workstation that means
tunnelling to it first:

```bash
ssh -L 5432:localhost:5432 your-miniflux-host
# then in .env:
# DB_URL=postgres://<user>:<password>@localhost:5432/<db>?sslmode=disable
```

## docker

```bash
make docker-build     # build the image
make docker-run       # run it against your .env
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
docker run --rm --env-file .env registry.gitlab.com/abelsonlive/feederss \
  python -m feederss publish
```

## deploying alongside miniflux

Add it to miniflux's own compose project, so it can reach miniflux's Postgres
over the compose network. It publishes outward only — no ports, no reverse
proxy, nothing to route:

```yaml
services:
  miniflux:
    image: miniflux/miniflux:latest
    # ...

  miniflux-postgres:
    image: postgres:16-alpine
    # ...

  feederss:
    image: registry.gitlab.com/abelsonlive/feederss:latest
    restart: unless-stopped
    environment:
      DB_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@miniflux-postgres/${POSTGRES_DB}?sslmode=disable
      APP_URL: https://miniflux.example.com
      REFRESH_INTERVAL_SECONDS: "3600"
      S3_BUCKET: your-bucket
      S3_ENDPOINT_URL: https://nyc3.digitaloceanspaces.com
      S3_REGION: nyc3
      S3_ACCESS_KEY_ID: ${S3_ACCESS_KEY_ID}
      S3_SECRET_ACCESS_KEY: ${S3_SECRET_ACCESS_KEY}
    depends_on:
      miniflux-postgres:
        condition: service_healthy
```

Then point a domain at the bucket. Providers differ in how they serve a static
site, and the details bite:

- Most need an explicit **website configuration** (an index document) before
  `/` returns `index.html` instead of a listing or a 403. On S3 that's
  `PutBucketWebsite`; the same call works on S3-compatible providers.
- Website endpoints usually route by **Host header**, which means the bucket
  has to be *named* after the domain (`feederss.example.com`, not `feederss`).
- **Custom-domain HTTPS** generally needs the provider's CDN or another proxy
  in front, because the bucket endpoint only presents the provider's own
  wildcard certificate.

The site links its own pages as `/`, so it needs a host that serves an index
document there.

AWS satisfies all three at once, which is what this is deployed on: enable
static website hosting on the bucket, make it public with a bucket policy
(*not* per-object ACLs, which modern buckets reject), then put CloudFront in
front with the **website** endpoint — `<bucket>.s3-website.<region>.amazonaws.com`
— as a *custom* origin over plain HTTP, plus an ACM cert for your domain. The
website endpoint is what supplies the index document; CloudFront supplies the
certificate.

Not every provider lets you combine them. DigitalOcean Spaces, for instance,
pulls in opposite directions: the `<bucket>.<region>-static.digitaloceanspaces.com`
endpoint honors the index document but only presents a
`*.<region>-static.digitaloceanspaces.com` cert, while the CDN endpoint
terminates TLS for your own domain but fronts the *origin* endpoint, so `/`
403s. Its CDN refuses to take the `-static` host as an origin, so you can't
have both without putting something like Cloudflare in front.

## releases

CI builds the image on every push and, on the default branch, pushes it to
this project's container registry as both
`registry.gitlab.com/abelsonlive/feederss:<short-sha>` and `:latest`. It
authenticates with GitLab's built-in job token, so there is nothing to
configure. The project is public, so the images pull anonymously.
