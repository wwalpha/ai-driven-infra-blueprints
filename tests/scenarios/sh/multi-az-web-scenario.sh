#!/usr/bin/env bash
set -euo pipefail

WEB_STACK_NAME="${1:-}"
AWS_REGION_VALUE="${AWS_REGION:-ap-northeast-1}"
EXPECTED_HTTP_STATUS="${EXPECTED_HTTP_STATUS:-200}"
EXPECTED_RESPONSE_TEXT="${EXPECTED_RESPONSE_TEXT:-Served via public ALB}"
EXPECTED_HEALTHY_TARGETS="${EXPECTED_HEALTHY_TARGETS:-2}"

if [[ -z "$WEB_STACK_NAME" ]]; then
  echo "usage: $0 <web-stack-name>" >&2
  exit 1
fi

stack_output() {
  local output_key="$1"
  aws cloudformation describe-stacks \
    --stack-name "$WEB_STACK_NAME" \
    --region "$AWS_REGION_VALUE" \
    --query "Stacks[0].Outputs[?OutputKey=='${output_key}'].OutputValue | [0]" \
    --output text
}

load_balancer_dns_name="$(stack_output LoadBalancerDnsName)"
target_group_arn="$(stack_output TargetGroupArn)"
instance_az1_id="$(stack_output WebInstanceAz1Id)"
instance_az2_id="$(stack_output WebInstanceAz2Id)"

if [[ "$load_balancer_dns_name" == "None" || -z "$load_balancer_dns_name" ]]; then
  echo "failed to resolve ALB DNS name from stack outputs" >&2
  exit 1
fi

echo "Checking HTTP response from http://$load_balancer_dns_name/"
response_body=""
for attempt in $(seq 1 30); do
  if response_body="$(curl --silent --show-error --max-time 10 "http://$load_balancer_dns_name/")"; then
    if grep -q "$EXPECTED_RESPONSE_TEXT" <<<"$response_body"; then
      break
    fi
  fi
  sleep 10
done

http_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "http://$load_balancer_dns_name/")"
if [[ "$http_status" != "$EXPECTED_HTTP_STATUS" ]]; then
  echo "unexpected HTTP status: $http_status" >&2
  exit 1
fi

if ! grep -q "$EXPECTED_RESPONSE_TEXT" <<<"$response_body"; then
  echo "response body did not contain expected text: $EXPECTED_RESPONSE_TEXT" >&2
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
  --instance-ids "$instance_az1_id" "$instance_az2_id" \
  --region "$AWS_REGION_VALUE" \
  --query "length(Reservations[].Instances[?PublicIpAddress!=null][])" \
  --output text)"

if [[ "$public_ip_count" != "0" ]]; then
  echo "expected no public IPs on web instances, found: $public_ip_count" >&2
  exit 1
fi

echo "Scenario test passed"
echo "- HTTP status: $http_status"
echo "- Healthy targets: $healthy_target_count"
echo "- Public IP count on instances: $public_ip_count"