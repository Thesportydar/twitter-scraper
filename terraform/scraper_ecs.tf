resource "aws_ecs_cluster" "twitter-scraper" {
  name = "twitter-scraper"
}

resource "aws_cloudwatch_log_group" "ecs_log_group" {
  name              = "/ecs/twitter-scraper"
  retention_in_days = 30
}

resource "aws_ecs_cluster_capacity_providers" "twitter-scraper" {
  cluster_name = aws_ecs_cluster.twitter-scraper.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE_SPOT"
  }
}

resource "aws_ecr_repository" "twitter-scraper" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "expire" {
  repository = aws_ecr_repository.twitter-scraper.name

  policy = <<EOF
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Delete untagged images older than 1 day",
      "selection": {
        "tagStatus": "untagged",
        "countType": "sinceImagePushed",
        "countUnit": "days",
        "countNumber": 3
      },
      "action": {
        "type": "expire"
      }
    }
  ]
}
EOF
}

//================================================================================
// IAM Roles
//================================================================================
resource "aws_iam_role" "ecs_execution_role" {
  name = var.ecs_execution_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_role_policy" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "twitter_scraper_task_role" {
  name = var.task_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "twitter_scraper_policy" {
  name = "twitter-scraper-policy"

  policy = jsonencode({
    "Version" : "2012-10-17",
    "Statement" : [
      {
        "Effect" : "Allow",
        "Action" : "cloudwatch:PutMetricData",
        "Resource" : "*"
      },
      {
        "Effect" : "Allow",
        "Action" : "s3:PutObject",
        "Resource" : [
          "arn:aws:s3:::${var.s3_bucket_name}/*"
        ]
      },
      {
        "Sid" : "SSMParameters",
        "Effect" : "Allow",
        "Action" : [
          "ssm:GetParameter"
        ],
        "Resource" : [
          aws_ssm_parameter.cookies.arn,
          aws_ssm_parameter.config.arn
        ]
      },
      {
        "Sid" : "EventBridge"
        "Effect" : "Allow",
        "Action" : [
          "events:PutEvents"
        ],
        "Resource" : [
          data.aws_cloudwatch_event_bus.default.arn
        ]
      },
      {
        "Effect" : "Allow",
        "Action" : [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:BatchGetItem",
          "dynamodb:BatchWriteItem",
          "dynamodb:Scan",
          "dynamodb:Query"
        ],
        "Resource" : [
          "${aws_dynamodb_table.tweet.arn}/index/*",
          aws_dynamodb_table.tweet.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "twitter_scraper_policy_attachment" {
  role       = aws_iam_role.twitter_scraper_task_role.name
  policy_arn = aws_iam_policy.twitter_scraper_policy.arn
}

//================================================================================
// Networking
//================================================================================
data "aws_vpc" "main" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

resource "aws_security_group" "ecs_task" {
  vpc_id = data.aws_vpc.main.id
  name   = "ecs-task"

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
