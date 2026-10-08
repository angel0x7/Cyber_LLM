
terraform {
  required_version = ">= 1.3.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
provider "aws" {
  region = "us-east-1"
}

# 1) Public S3 bucket with no versioning/encryption
resource "aws_s3_bucket" "public_assets" {
  bucket = "demo-public-assets-example-llmsec"
  acl    = "public-read"   # Intentional misconfig
  tags = { Purpose = "demo" }
}

# 2) Security group open to world
resource "aws_security_group" "open_sg" {
  name        = "open-sg"
  description = "Allows all inbound"
  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 3) Overly permissive IAM policy
resource "aws_iam_policy" "admin_policy" {
  name   = "AdminPolicy"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action   = "*",
      Effect   = "Allow",
      Resource = "*"
    }]
  })
}
