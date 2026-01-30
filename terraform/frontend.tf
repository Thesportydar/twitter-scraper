//================================================================================
// Cloudfront
//================================================================================
resource "aws_cloudfront_origin_access_control" "default" {
  name                              = "s3-oac-${var.domain}"
  description                       = "OAC for ${var.domain}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "rewrite" {
  name    = "rewrite-${replace(var.domain, ".", "-")}"
  runtime = "cloudfront-js-1.0"
  comment = "Rewrite rules for SPA and folders"
  publish = true
  code    = file("${path.module}/functions/rewrite.js")
}

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

resource "aws_cloudfront_distribution" "s3_distribution" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "S3 distribution for ${var.domain}"
  default_root_object = "index.html"

  origin {
    origin_path              = "/site"
    domain_name              = aws_s3_bucket.scraper.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.default.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = local.s3_origin_id
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    cache_policy_id = data.aws_cloudfront_cache_policy.caching_optimized.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.rewrite.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = local.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  aliases = [var.domain]
}

//================================================================================
// ACM / Route53
//================================================================================
resource "aws_acm_certificate" "wildcard" {
  count = var.certificate_arn == "" ? 1 : 0

  domain_name               = "*.${var.domain}"
  validation_method         = "DNS"
  subject_alternative_names = [var.domain]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  provider = aws.route53
  for_each = var.certificate_arn != "" ? {} : {
    for dvo in aws_acm_certificate.wildcard[0].domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.domain_zone.zone_id
}

resource "aws_acm_certificate_validation" "cert" {
  count = var.certificate_arn == "" ? 1 : 0

  certificate_arn         = aws_acm_certificate.wildcard[0].arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

resource "aws_route53_record" "www" {
  provider = aws.route53
  zone_id  = data.aws_route53_zone.domain_zone.zone_id
  name     = var.domain
  type     = "A"

  alias {
    name                   = aws_cloudfront_distribution.s3_distribution.domain_name
    zone_id                = aws_cloudfront_distribution.s3_distribution.hosted_zone_id
    evaluate_target_health = false
  }
}
