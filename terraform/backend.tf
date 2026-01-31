terraform {
  backend "s3" {
    key = "twitter-scraper/terraform.tfstate"
  }
}
