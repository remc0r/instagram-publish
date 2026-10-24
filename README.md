# instagram-publish

Publish a photo, video, Reel, carousel or Story on Instagram with the Graph API, in one call.

## Prerequisites

- An Instagram **Business or Creator** account.
- A Meta app with the **Instagram** product ([developers.facebook.com/apps](https://developers.facebook.com/apps)). The app can stay in Development mode if you only post on your own account.
- Media must be **public HTTPS URLs** (Instagram downloads them itself): S3, your server, etc.

## Get a token and an account id

Two ways, depending on how you authenticate. **Option A is simpler and is the default.**

### Option A: Instagram Login (default, `--login instagram`)

No Facebook Page needed. The token is valid **60 days**.

1. In the app dashboard: **Roles → Roles**, add your Instagram account as **Instagram Tester**.
2. Accept the invite on [instagram.com/accounts/manage_access](https://www.instagram.com/accounts/manage_access/) (tab *Tester Invites*).
3. In the dashboard: **Instagram → API setup with Instagram business login → Add account → Generate token**.
4. The account id shown next to it is your `IG_USER_ID`.

Official guide: [Instagram API with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started).

### Refresh the token (Option A only)

A token expires after 60 days. Refresh it before that: it must be older than 24h and not expired, and each refresh gives 60 more days. Run it about once a month.

```python
from instagram_publish import InstagramClient

ig = InstagramClient()                   # uses your current IG_ACCESS_TOKEN
result = ig.refresh_token()              # calls Meta
new_token = result["access_token"]       # save it: file, database, secret manager...
print(result["expires_in"] // 86400)     # days of validity (about 60)
```

After a refresh, `ig` itself uses the new token right away. To keep it for next time, pass `token_file`: the client then reads the token from that file and rewrites it (mode 600) on every refresh.

```python
ig = InstagramClient(token_file="~/.ig_token")   # first run: seeded from IG_ACCESS_TOKEN if the file doesn't exist yet
ig.refresh_token()                               # new token saved in ~/.ig_token
```

Once the file exists it wins over `access_token` and `IG_ACCESS_TOKEN`. Without `token_file`, `refresh_token()` does not store anything: save `new_token` yourself (an environment variable cannot be updated durably from Python).

From the shell (or a monthly cron), with a token file nothing else is needed:

```bash
instagram-publish --token-file ~/.ig_token refresh-token
instagram-publish --token-file ~/.ig_token publish https://example.com/photo.jpg
```

Without `--token-file`, `refresh-token` prints the new token and you must save it yourself.

### Option B: Facebook Login (`--login facebook`)

For when you already have a Facebook Login token (e.g. from the [Graph API Explorer](https://developers.facebook.com/tools/explorer/)). Requires an Instagram account linked to a Facebook Page and the permissions `instagram_basic`, `instagram_content_publish`, `pages_show_list`. Explorer tokens last about 1 hour and cannot be refreshed with `refresh-token`.

`IG_USER_ID` is the `instagram_business_account.id` returned by `GET me/accounts?fields=instagram_business_account`.

### What `--login` does

It only tells the tool which server your token belongs to: `instagram` → `graph.instagram.com`, `facebook` → `graph.facebook.com`. A token only works on the server that issued it, so a wrong value gives an auth error. In Python: `InstagramClient(login="facebook")`. In the CLI, put it before the subcommand: `instagram-publish --login facebook publish <url>`.

## Install

```bash
pip install instagram-publish   # or: uvx instagram-publish ...
export IG_ACCESS_TOKEN="..."
export IG_USER_ID="..."
```

Env vars are the default; you can also pass `access_token=` and `user_id=` to `InstagramClient`.

## Usage

```python
from instagram_publish import InstagramClient

ig = InstagramClient()  # reads IG_ACCESS_TOKEN and IG_USER_ID
ig.publish("https://example.com/photo.jpg", "My caption")               # photo
ig.publish("https://example.com/clip.mp4", "My Reel")                   # video -> Reel
ig.publish(["https://example.com/1.jpg", "https://example.com/2.mp4"])  # carousel (2-10 items)
ig.publish("https://example.com/photo.jpg", story=True)                 # story (no caption)
```

CLI:

```bash
instagram-publish publish https://example.com/photo.jpg -c "My caption"
instagram-publish publish https://example.com/photo.jpg --story
```

Options: `--ai-generated` flags the post as AI-generated, `--api-version` overrides the Graph API version (default `v26.0`), `--login` picks the token flavour (see above).

Errors raise `InstagramError`.

## Security notes

- The token is sent in an `Authorization` header and is never put in error messages. The one exception is `refresh_token()`: Meta's refresh endpoint takes the token as a URL parameter, so that URL can appear in debug logs (`urllib3`) or proxy logs. Keep debug logging off in production.
- `token_file` is written atomically with mode 600. If it is readable by other users you get a warning. Once it exists it wins over `access_token` and `IG_ACCESS_TOKEN`: delete it if you want to switch to a new token.
- Media must be `https://` URLs; Instagram fetches them itself, so never pass URLs you don't control or trust. Redirects are not followed. `api_version` and `IG_USER_ID` are validated.
- Proxy variables (`HTTPS_PROXY`, `REQUESTS_CA_BUNDLE`) are honoured: the token goes through them.
- Publishing is not retried automatically, to avoid duplicate posts. If `publish()` times out, check your profile before retrying.

## Migrating from 0.x

1.0 is a rewrite: `config.py`, Filestack and local file paths are gone (media are public HTTPS URLs), and the entry point is `InstagramClient(...).publish(...)`.

## Development

```bash
uv run pytest
```
