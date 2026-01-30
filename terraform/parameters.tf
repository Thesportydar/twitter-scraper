resource "aws_ssm_parameter" "cookies" {
  name  = "/twitter-scraper/cookies"
  type  = "SecureString"
  value = "PLACEHOLDER"
}

resource "aws_ssm_parameter" "config" {
  name  = "/twitter-scraper/user-configs"
  type  = "String"
  value = "PLACEHOLDER"
}

resource "aws_ssm_parameter" "github_token" {
  name  = "/twitter-scraper/GITHUB_TOKEN"
  type  = "SecureString"
  value = "PLACEHOLDER"
}

resource "aws_ssm_parameter" "openai_api_key" {
  name  = "/twitter-scraper/OPENAI_API_KEY"
  type  = "SecureString"
  value = "PLACEHOLDER"
}
