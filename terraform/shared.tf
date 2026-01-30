data "aws_route53_zone" "domain_zone" {
  provider = aws.route53
  name     = var.hosted_zone_name
}

data "aws_cloudwatch_event_bus" "default" {
  name = "default"
}

//================================================================================
// S3
//================================================================================
resource "aws_s3_bucket" "scraper" {
  bucket        = var.s3_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "scraper_versioning" {
  bucket = aws_s3_bucket.scraper.id

  versioning_configuration {
    status = "Disabled"
  }
}

resource "aws_s3_bucket_public_access_block" "scraper_public_access" {
  bucket = aws_s3_bucket.scraper.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "scraper_sse" {
  bucket = aws_s3_bucket.scraper.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "scraper_policy" {
  bucket = aws_s3_bucket.scraper.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action = "s3:GetObject"
        Resource = [
          "${aws_s3_bucket.scraper.arn}/*"
        ]
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.s3_distribution.arn
          }
        }
      }
    ]
  })
}

//================================================================================
// DynamoDB
//================================================================================
resource "aws_dynamodb_table" "tweet" {
  name         = var.dynamodb_tweet_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "Id"

  attribute {
    name = "Id"
    type = "S"
  }

  attribute {
    name = "User"
    type = "S"
  }

  attribute {
    name = "ScrapedAt"
    type = "S"
  }

  global_secondary_index {
    name            = "UserIndex"
    hash_key        = "User"
    range_key       = "ScrapedAt"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ExpireAt"
    enabled        = true
  }
}
