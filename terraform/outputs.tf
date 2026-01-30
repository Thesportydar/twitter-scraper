output "cloudfront_distribution_domain_name" {
  description = "The domain name of the CloudFront distribution"
  value       = aws_cloudfront_distribution.s3_distribution.domain_name
}

output "cloudfront_distribution_id" {
  description = "The ID of the CloudFront distribution"
  value       = aws_cloudfront_distribution.s3_distribution.id
}

output "s3_bucket_name" {
  description = "The name of the S3 bucket"
  value       = aws_s3_bucket.scraper.id
}

output "ecr_repository_url" {
  description = "The URL of the ECR repository"
  value       = aws_ecr_repository.twitter-scraper.repository_url
}

output "processor_lambda_function_name" {
  description = "The name of the processor Lambda function"
  value       = aws_lambda_function.processor_lambda.function_name
}

output "dispatcher_lambda_function_name" {
  description = "The name of the dispatcher Lambda function"
  value       = aws_lambda_function.dispatcher.function_name
}

output "dynamodb_table_name" {
  description = "The name of the DynamoDB table"
  value       = aws_dynamodb_table.tweet.name
}
