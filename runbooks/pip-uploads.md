# Runbook — Pip's uploads bucket (D-781)

When: once, before files can be attached to Pip on a deployment; after any edit to
`infra/object-lifecycle/copilot-uploads-policy.json`; and when the uploads token is rotated.

What it is: a private R2 bucket of its own for files people attach to Pip, written and read
ONLY by the API with a dedicated R2 API token scoped to that bucket. The browser never talks
to the bucket, so the bucket needs no CORS rule and no public access, and no URL to it ever
leaves the API. Until all three settings below are set, attaching a file is refused with
"Files can't be attached right now" (`copilot_uploads_unavailable`) and everything else in
Pip works as before.

Nothing below prints a file name, a key or a file's contents.

---

## 1. Create the bucket

Cloudflare dashboard → R2 → Create bucket.

- Name: anything not reused, e.g. `calevate-pip-uploads`. It holds no secret.
- Location: the same hint as the main bucket (Asia-Pacific). R2 fixes placement at the first
  create for a name (`infra/README.md` §5 item 2), so choose before creating.
- Public access: leave OFF. Do not add a custom domain or an `r2.dev` URL: nothing should
  be able to read this bucket except the API's token.
- CORS: none. The browser does not reach R2.

## 2. Create the dedicated token

Cloudflare dashboard → R2 → Manage R2 API Tokens → Create API token.

- Permissions: **Object Read & Write**.
- Specify bucket(s): **only** the bucket from step 1. Never "Apply to all buckets": this
  token must not be able to reach recordings, transcripts or documents.
- TTL: none, or your rotation period.
- Copy the **Access Key ID** and **Secret Access Key** shown once.

## 3. Put them in the console

Admin console → Ops → Config (superadmin only):

| Setting | Where | Value |
|---|---|---|
| `copilot_upload_bucket` | Config, Infrastructure → Storage, "Pip uploads bucket" | the bucket name |
| `copilot_upload_access_key_id` | Config, Infrastructure → Storage, "Pip uploads access key ID" | the Access Key ID (not secret; it identifies the token) |
| `copilot_upload_secret_access_key` | Credentials (Secrets panel) | the Secret Access Key — stored encrypted, never shown again |

All three apply live: `workers/storage._upload_client()` rebuilds when any changes. The
endpoint is the main object-store endpoint (`object_store_endpoint`), the account's
`https://<account>.r2.cloudflarestorage.com`.

## 4. Apply the lifecycle rule

The bucket-level backstop: anything older than 30 days is deleted, and an incomplete
multipart upload (an upload whose request died) is aborted after one day. The app deletes
files much sooner — on removal, "start again", the end of the person's last session, and
account erasure; this rule catches anything those paths missed.

```
python infra/object-lifecycle/apply_lifecycle.py \
    --endpoint https://<account>.r2.cloudflarestorage.com \
    --bucket <uploads bucket> \
    --policy infra/object-lifecycle/copilot-uploads-policy.json \
    --max-tenant-ttl-days 90
# review the printed diff, then re-run with --apply
```

(`--max-tenant-ttl-days` is required by the script for the main bucket's recording floor and
has no effect on this policy, which has no `recordings/` rule.) Neither the uploads token
nor the main bucket's token can run it: both are Object Read & Write, which cannot edit
bucket configuration (developers.cloudflare.com/r2/api/tokens, read 28 Oct 2026). Use a
short-lived **Admin Read & Write** token in that shell only, and delete it after. Or enter
the two rules in the dashboard instead (bucket → Settings → Object Lifecycle Rules → Add
rule): prefix `copilot-uploads/`, delete after 30 days; same prefix, abort incomplete
multipart uploads after 1 day.

## 5. The nginx change

`infra/nginx/calevate.conf.template` gives `POST /v1/copilot/uploads` and
`POST /v1/admin/copilot/uploads` a 20 MB body limit and `proxy_request_buffering off`, and lowers the api vhost's default body limit to the app's own
2 MB. The deploy prints the `sudo install` lines for the rendered nginx config; run them,
then `sudo nginx -t && sudo systemctl reload nginx`.

## 6. Check it

1. Open Pip, attach a small `.txt` file: it shows "Attached".
2. Ask a question about it: Pip answers from it.
   Attach a small PDF and ask about it: Pip reads it with Gemini (a PDF turn never uses
   Azure or Sarvam; if Gemini cannot read it, Pip says it can't take PDFs right now).
3. Start again: the file is gone (the bucket listing for that account's prefix is empty).

## Rotating the token

Create a new token (step 2), set the two values (step 3), confirm an upload works, then
delete the old token in Cloudflare.

## If it is not working

- "Files can't be attached right now" on every upload: a setting is missing, or the token
  cannot reach the bucket (wrong bucket in step 2). The API logs `upload_*_failed` with the
  error type only.
- Uploads over 2 MB fail with an nginx 413 page: step 5 was not applied.
