# UNVALIDATED — read infra/README.md §5 before trusting this file.
#
# `terraform init` and `terraform validate` could NOT be run in the environment that
# wrote this module: registry.terraform.io is blocked by egress policy there, so no
# provider schema was ever downloaded and no resource attribute below has been checked
# against a real provider. `terraform fmt -check` passes; that proves HCL syntax and
# nothing else. The first human with registry access must run `terraform init` and
# `terraform validate` and reconcile any schema drift BEFORE this is applied anywhere.
#
# WHY THE AWS PROVIDER FOR A CLOUDFLARE BUCKET. Production object storage is Cloudflare
# R2 (DEPLOYMENT.md §1, TRD §2). R2 speaks the S3 API, including
# PutBucketLifecycleConfiguration, so `aws_s3_bucket_lifecycle_configuration` pointed at
# the R2 endpoint configures it — and the same module then works unchanged against DO
# Spaces (the documented alternative in DEV-SETUP.md) and against MinIO locally. The
# Cloudflare provider's own R2 lifecycle resource may well be the better long-term
# home; it was not used here precisely because its schema could not be verified, and a
# resource nobody has checked is worse than a resource everybody knows.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  # R2/Spaces/MinIO are not AWS. Every AWS-specific preflight the provider would
  # otherwise perform has to be skipped or it will try to talk to AWS endpoints.
  #
  # `region = "auto"` IS THE SIGV4 CREDENTIAL SCOPE, NOT A PLACEMENT (D-450). It is the
  # string the signature is computed over, and R2 requires exactly this one. The bucket's
  # PHYSICAL placement is a separate thing — R2's `CreateBucket` location hint, decided as
  # `apac` — and it is set once, by a human, at the first creation of the bucket NAME
  # (`infra/README.md` §5 item 2). Writing "apac" on the line below buys no placement
  # whatsoever and breaks every request with `SignatureDoesNotMatch`, which is a failure
  # nobody debugging placement would think to look for. Leave it alone.
  #
  # And this module CANNOT set the hint even if you wanted it to: its only resource is
  # `aws_s3_bucket_lifecycle_configuration` against a bucket that already exists. There is
  # deliberately no `aws_s3_bucket` here — the AWS provider has no way to send R2's hint,
  # so a bucket resource added to "own" the placement would create the bucket in the WRONG
  # place, permanently, while looking like it owned the decision. The hint's only honest
  # home is the human checklist.
  region                      = "auto"
  skip_credentials_validation = true
  skip_region_validation      = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true

  endpoints {
    s3 = var.object_store_endpoint
  }

  # Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in the environment,
  # sourced from the secrets manager at deploy time. Never a variable with a default,
  # never a file in this repository (CLAUDE.md: "Store secrets in DB/env-committed
  # files" is a Do NOT).
}
