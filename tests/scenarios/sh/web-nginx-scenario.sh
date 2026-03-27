#!/usr/bin/env bash
set -euo pipefail

NETWORK_STACK_NAME="${1:-cfn-stack-dev-webnginx-network01}"
SECURITY_STACK_NAME="${2:-cfn-stack-dev-webnginx-security01}"
APP_STACK_NAME="${3:-cfn-stack-dev-webnginx-app01}"
AWS_REGION_VALUE="${AWS_REGION:-ap-northeast-1}"
EXPECTED_HTTP_STATUS="${EXPECTED_HTTP_STATUS:-200}"
EXPECTED_HEALTHY_TARGETS="${EXPECTED_HEALTHY_TARGETS:-2}"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command not found: $command_name" >&2
    exit 1
  fi
}

stack_output() {
  local stack_name="$1"
  local output_key="$2"

  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$AWS_REGION_VALUE" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue | [0]" \
    --output text
}

stack_status() {
  local stack_name="$1"

  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$AWS_REGION_VALUE" \
    --query "Stacks[0].StackStatus" \
    --output text
}

require_command aws
require_command curl
require_command grep

for stack_name in "$NETWORK_STACK_NAME" "$SECURITY_STACK_NAME" "$APP_STACK_NAME"; do
  current_status="$(stack_status "$stack_name")"
  echo "stack status: $stack_name -> $current_status"
  if [[ "$current_status" != "CREATE_COMPLETE" && "$current_status" != "UPDATE_COMPLETE" ]]; then
    echo "unexpected stack status for $stack_name: $current_status" >&2
    exit 1
  fi
done

alb_dns_name="$(stack_output "$APP_STACK_NAME" AlbDnsName)"
target_group_arn="$(stack_output "$APP_STACK_NAME" TargetGroupArn)"
ec2_az1_instance_id="$(stack_output "$APP_STACK_NAME" Ec2Az1InstanceId)"
ec2_az2_instance_id="$(stack_output "$APP_STACK_NAME" Ec2Az2InstanceId)"

if [[ -z "$alb_dns_name" || "$alb_dns_name" == "None" ]]; then
  echo "AlbDnsName output was empty" >&2
  exit 1
fi

echo "resolving ALB endpoint: http://$alb_dns_name/"
response_body=""
http_status=""

for attempt in $(seq 1 30); do
  if response_body="$(curl --silent --show-error --max-time 10 "http://$alb_dns_name/")"; then
    http_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "http://$alb_dns_name/")"
    if [[ "$http_status" == "$EXPECTED_HTTP_STATUS" ]] && grep -Eiq 'web-nginx|instance-id=|availability-zone=' <<<"$response_body"; then
      break
    fi
  fi
  sleep 10
done

if [[ "$http_status" != "$EXPECTED_HTTP_STATUS" ]]; then
  echo "unexpected HTTP status from ALB: $http_status" >&2
  exit 1
fi

if ! grep -Eiq 'web-nginx|instance-id=|availability-zone=' <<<"$response_body"; then
  echo "response body did not contain expected NGINX metadata" >&2
  exit 1
fi

healthy_target_count="$(aws elbv2 describe-target-health \
  --target-group-arn "$target_group_arn" \
  --region "$AWS_REGION_VALUE" \
  --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" \
  --output text)"

if [[ "$healthy_target_count" != "$EXPECTED_HEALTHY_TARGETS" ]]; then
  echo "unexpected healthy target count: $healthy_target_count" >&2
  exit 1
fi

public_ip_count="$(aws ec2 describe-instances \
  --instance-ids "$ec2_az1_instance_id" "$ec2_az2_instance_id" \
  --region "$AWS_REGION_VALUE" \
  --query "length(Reservations[].Instances[?PublicIpAddress!=null][])" \
  --output text)"

if [[ "$public_ip_count" != "0" ]]; then
  echo "EC2 instances unexpectedly have public IPs: $public_ip_count" >&2
  exit 1
fi

distinct_az_count="$(aws ec2 describe-instances \
  --instance-ids "$ec2_az1_instance_id" "$ec2_az2_instance_id" \
  --region "$AWS_REGION_VALUE" \
  --query "Reservations[].Instances[].Placement.AvailabilityZone" \
  --output text | tr '\t' '\n' | sort -u | wc -l | tr -d ' ')"

if [[ "$distinct_az_count" != "2" ]]; then
  echo "instances are not distributed across two AZs: $distinct_az_count" >&2
  exit 1
fi

instance_profile_count="$(aws ec2 describe-instances \
  --instance-ids "$ec2_az1_instance_id" "$ec2_az2_instance_id" \
  --region "$AWS_REGION_VALUE" \
  --query "length(Reservations[].Instances[?IamInstanceProfile.Arn!=null][])" \
  --output text)"

if [[ "$instance_profile_count" != "2" ]]; then
  echo "missing IAM instance profile on one or more instances: $instance_profile_count" >&2
  exit 1
fi

echo "Scenario test passed"
echo "- HTTP status: $http_status"
echo "- Healthy targets: $healthy_target_count"
echo "- Public IP count: $public_ip_count"
echo "- Distinct AZ count: $distinct_az_count"
echo "- IAM instance profile count: $instance_profile_count"