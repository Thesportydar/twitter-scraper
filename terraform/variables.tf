variable "environment" {
  description = "The deployment environment (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "The name of the project"
  type        = string
}

variable "terraform_execution_role_arn" {
  description = "The ARN of the role to assume for Terraform execution"
  type        = string
}

variable "dispatcher_function_name" {
  description = "The name of the scheduler Lambda function"
  type        = string
}

variable "processor_function_name" {
  description = "The name of the processor Lambda function"
  type        = string
}

variable "s3_bucket_name" {
  description = "Bucket name"
  type        = string
}

variable "dynamodb_tweet_table_name" {
  description = "Name of the tweet table"
  type        = string
}

variable "task_family_name" {
  description = "The name of the ECS task family"
  type        = string
}

variable "domain" {
  description = "The domain name (e.g. app.example.com)"
  type        = string
}

variable "hosted_zone_name" {
  description = "The Route53 hosted zone name (e.g. example.com)"
  type        = string
}

variable "certificate_arn" {
  description = "The ARN of the ACM certificate"
  type        = string
  default     = ""
}

variable "route53_role_arn" {
  description = "The ARN of the role to assume for Route53 operations"
  type        = string
}

variable "github_owner" {
  description = "The owner of the GitHub repository"
  type        = string
}

variable "github_repo" {
  description = "The name of the GitHub repository"
  type        = string
}

variable "ecr_repository_name" {
  description = "Name of the ECR repository"
  type        = string
  default     = "twitter-scraper"
}

variable "ecs_execution_role_name" {
  description = "Name of the ECS execution role"
  type        = string
  default     = "ecsTaskExecutionRole"
}

variable "task_role_name" {
  description = "Name of the ECS task role"
  type        = string
  default     = "TwitterScraperTaskRole"
}
