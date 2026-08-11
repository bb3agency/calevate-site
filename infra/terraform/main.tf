# The object-store lifecycle rule that `apps/workers/retention.py`,
# `apps/workers/storage.py` and `apps/api/compliance/deletion.py` have been naming as
# the mechanism that removes recording audio. Until this module existed it did not, and
# the bytes were deleted by nothing. See infra/README.md for what it does and does not
# promise — in particular, it is a growth CEILING, not per-tenant retention.

locals {
  # ONE source of truth, shared with infra/object-lifecycle/apply_lifecycle.py and
  # pinned by tests/object_lifecycle_test.py. Terraform reads the same document the
  # script applies, so the two representations cannot drift into disagreeing about
  # what the lifecycle rule is.
  policy = jsondecode(file("${path.module}/../object-lifecycle/policy.json"))

  rules = local.policy.Rules

  # Every enabled rule whose prefix can reach objects under `recordings/` — including a
  # bucket-root catch-all, which would delete recordings just as effectively as a rule
  # that names them.
  recording_expiry_days = [
    for r in local.rules : try(r.Expiration.Days, null)
    if r.Status == "Enabled"
    && try(r.Expiration.Days, null) != null
    && (startswith("recordings/", try(r.Filter.Prefix, "")) || startswith(try(r.Filter.Prefix, ""), "recordings/"))
  ]

  min_recording_expiry_days = length(local.recording_expiry_days) > 0 ? min(local.recording_expiry_days...) : null
}

resource "aws_s3_bucket_lifecycle_configuration" "calevate" {
  bucket = var.object_store_bucket

  lifecycle {
    # GUARD 1 — the TRAI floor (SECURITY-COMPLIANCE §1), already enforced by a DB CHECK
    # on retention_policies and by RECORDING_FLOOR_DAYS in apps/workers/retention.py.
    # This is the third place, and the only one that touches bytes rather than a
    # pointer. A plan that would expire recordings sooner fails here instead of
    # deleting evidence that a call was compliant.
    precondition {
      condition     = local.min_recording_expiry_days == null || local.min_recording_expiry_days >= 90
      error_message = "A rule expires recordings under 90 days. That is below the TRAI retention floor (SECURITY-COMPLIANCE §1)."
    }

    # GUARD 2 — the ceiling must sit above every live tenant policy, or it silently
    # becomes the retention mechanism for the tenants it undercuts, deleting a BFSI
    # client's recordings before their regulator's minimum.
    precondition {
      condition     = local.min_recording_expiry_days == null || local.min_recording_expiry_days >= var.max_tenant_recording_ttl_days
      error_message = "A rule expires recordings sooner than the longest configured tenant recording TTL. Raise the ceiling in policy.json, or correct max_tenant_recording_ttl_days."
    }
  }

  dynamic "rule" {
    for_each = local.rules

    content {
      id     = rule.value.ID
      status = rule.value.Status

      filter {
        prefix = try(rule.value.Filter.Prefix, "")
      }

      dynamic "expiration" {
        for_each = try(rule.value.Expiration, null) == null ? [] : [rule.value.Expiration]
        content {
          days = expiration.value.Days
        }
      }

      dynamic "abort_incomplete_multipart_upload" {
        for_each = try(rule.value.AbortIncompleteMultipartUpload, null) == null ? [] : [rule.value.AbortIncompleteMultipartUpload]
        content {
          days_after_initiation = abort_incomplete_multipart_upload.value.DaysAfterInitiation
        }
      }
    }
  }
}

output "recording_expiry_days" {
  description = "Days after which recording objects become eligible for deletion. Eligibility, not a deletion receipt — expiry is asynchronous on every S3-compatible store."
  value       = local.min_recording_expiry_days
}
