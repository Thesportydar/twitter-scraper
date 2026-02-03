resource "aws_lambda_function" "dispatcher" {
  filename         = data.archive_file.dispatcher_zip.output_path
  function_name    = var.dispatcher_function_name
  role             = aws_iam_role.dispatcher_role.arn
  handler          = "index.handler"
  source_code_hash = data.archive_file.dispatcher_zip.output_base64sha256
  runtime          = "nodejs22.x"
  architectures    = ["arm64"]
  timeout          = 3

  environment {
    variables = {
      ECS_CLUSTER         = aws_ecs_cluster.twitter-scraper.name
      ECS_TASK_DEFINITION = var.task_family_name
      ECS_SUBNETS         = join(",", data.aws_subnets.default.ids)
      ECS_SECURITY_GROUPS = aws_security_group.ecs_task.id
    }
  }

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  depends_on = [
    aws_cloudwatch_log_group.dispatcher_log_group
  ]
}

resource "aws_cloudwatch_log_group" "dispatcher_log_group" {
  name              = "/aws/lambda/${var.dispatcher_function_name}"
  retention_in_days = 3
}

data "archive_file" "dispatcher_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/dispatcher"
  output_path = "${path.module}/../lambdas/dispatcher.zip"
}

//================================================================================
// IAM
//================================================================================
resource "aws_iam_role" "dispatcher_role" {
  name = "lambda-dispatcher-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "dispatcher_policy" {
  name = "lambda-dispatcher-execution-policy"
  role = aws_iam_role.dispatcher_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole",
          "ecs:RunTask",
        ]
        Resource = [
          "arn:aws:ecs:*:*:task-definition/${var.task_family_name}:*",
          aws_iam_role.ecs_execution_role.arn,
          aws_iam_role.twitter_scraper_task_role.arn
        ]
      }
    ]
  })
}

//================================================================================
// Scheduler
//================================================================================
resource "aws_scheduler_schedule" "scheduler" {
  name       = "trigger-schedule-twitter-scraper"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "cron(0 1,13,16,23 * * ? *)"

  target {
    arn      = aws_lambda_function.dispatcher.arn
    role_arn = aws_iam_role.eventbridge_scheduler_role.arn
  }
}

resource "aws_iam_role" "eventbridge_scheduler_role" {
  name = "eventbridge-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "scheduler.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_scheduler_policy" {
  name = "eventbridge-scheduler-policy"
  role = aws_iam_role.eventbridge_scheduler_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          aws_lambda_function.dispatcher.arn,
          "${aws_lambda_function.dispatcher.arn}:*"
        ]
      }
    ]
  })
}
