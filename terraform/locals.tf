locals {
  certificate_arn = (
    var.certificate_arn != ""
    ? var.certificate_arn
    : aws_acm_certificate.wildcard[0].arn
  )

  s3_origin_id = "S3-${var.s3_bucket_name}"
}
