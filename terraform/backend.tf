terraform {
  backend "s3" {
    key = "dev/twitter-scraper/terraform.tfstate"
  }
}
