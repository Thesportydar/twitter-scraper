resource "aws_cloudwatch_log_group" "processor_lambda" {
  name              = "/aws/lambda/${var.processor_function_name}"
  retention_in_days = 14
}

data "archive_file" "processor_lambda" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/processor"
  output_path = "${path.module}/../lambdas/processor.zip"
}

resource "aws_lambda_layer_version" "openai_layer" {
  layer_name               = "openai_layer"
  filename                 = "${path.module}/../lambdas/layer/layer.zip"
  description              = "OpenAI layer"
  compatible_runtimes      = ["nodejs22.x"]
  compatible_architectures = ["x86_64"]
}

resource "aws_lambda_function" "processor_lambda" {
  function_name = var.processor_function_name
  role          = aws_iam_role.processor_role.arn
  filename      = data.archive_file.processor_lambda.output_path
  code_sha256   = data.archive_file.processor_lambda.output_base64sha256

  runtime = "nodejs22.x"
  handler = "index.handler"
  timeout = 180

  layers = [aws_lambda_layer_version.openai_layer.arn]

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  depends_on = [
    aws_iam_role_policy.processor_policy,
    aws_cloudwatch_log_group.processor_lambda
  ]

  environment {
    variables = {
      ENVIRONMENT  = var.environment
      LOG_LEVEL    = "INFO"
      GITHUB_OWNER = var.github_owner
      GITHUB_REPO  = var.github_repo
    }
  }
}

//================================================================================
// IAM
//================================================================================
resource "aws_iam_role" "processor_role" {
  name = "lambda-processor-execution-role"

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

resource "aws_iam_role_policy" "processor_policy" {
  name = "lambda-processor-execution-policy"
  role = aws_iam_role.processor_role.id

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
          "s3:GetObject",
          "s3:ListBucket",
          "s3:Describe*",
          "s3-object-lambda:Get*",
          "s3-object-lambda:List*"
        ]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}/*",
          "arn:aws:s3:::${var.s3_bucket_name}"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = [
          aws_ssm_parameter.github_token.arn,
          aws_ssm_parameter.openai_api_key.arn
        ]
      }
    ]
  })
}

//================================================================================
// CloudWatch Event Trigger
//================================================================================
resource "aws_cloudwatch_event_rule" "tweets_uploaded" {
  name = "twitter-scraper-tweets-uploaded"

  event_pattern = jsonencode({
    source      = ["twitter.scraper"]
    detail-type = ["TweetsUploaded"]
  })
}

resource "aws_cloudwatch_event_target" "processor_lambda" {
  rule      = aws_cloudwatch_event_rule.tweets_uploaded.name
  target_id = "SendToProcessorLambda"
  arn       = aws_lambda_function.processor_lambda.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.tweets_uploaded.arn
}
