provider "aws" {
  region  = "us-east-1"
  profile = "${var.environment}-terraform-admin"

  assume_role {
    role_arn = var.terraform_execution_role_arn
  }

  default_tags {
    tags = {
      ManagedBy   = "Terraform"
      Environment = var.environment
      Project     = var.project_name
    }
  }
}

provider "aws" {
  alias   = "route53"
  region  = "us-east-1"
  profile = "${var.environment}-terraform-admin"

  assume_role {
    role_arn = var.route53_role_arn
  }

  default_tags {
    tags = {
      ManagedBy   = "Terraform"
      Environment = var.environment
      Project     = var.project_name
    }
  }
}
