variable "object_store_endpoint" {
  description = "S3-compatible endpoint. R2: https://<account-id>.r2.cloudflarestorage.com"
  type        = string
}

variable "object_store_bucket" {
  description = "Bucket holding recordings/ and engine-payloads/. No default — a wrong bucket name here is a wrong bucket's data."
  type        = string
}

variable "max_tenant_recording_ttl_days" {
  description = <<-EOT
    The longest `ttl_days` any tenant currently has on a `recording` retention policy.

    This is not decoration. `retention_policies.ttl_days` has NO upper bound in the
    schema (the only CHECK is `data_category != 'recording' OR ttl_days >= 90`), and a
    BFSI client can lawfully be configured well past the 180-day default — RBI's
    two-year rule is called out in SECURITY-COMPLIANCE §1. The bucket ceiling below
    must sit at or above this number, or the lifecycle rule deletes a client's
    recordings before the regulator's own minimum.

    Get it from the database, do not guess — the query is in
    runbooks/object-lifecycle.md. Re-check it whenever a client's policy changes.
  EOT
  type        = number

  validation {
    condition     = var.max_tenant_recording_ttl_days >= 90
    error_message = "A recording TTL below 90 days cannot exist (TRAI floor, SECURITY-COMPLIANCE §1). Re-run the query; something is wrong."
  }
}
