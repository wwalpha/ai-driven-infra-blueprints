param(
    [string]$NetworkStackName = "cfn-stack-dev-webnginx-network01",
    [string]$SecurityStackName = "cfn-stack-dev-webnginx-security01",
    [string]$AppStackName = "cfn-stack-dev-webnginx-app01",
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "ap-northeast-1" }),
    [int]$ExpectedHttpStatus = 200,
    [int]$ExpectedHealthyTargets = 2
)

$ErrorActionPreference = "Stop"

function Get-StackOutput {
    param(
        [string]$StackName,
        [string]$OutputKey
    )

    aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region `
        --query "Stacks[0].Outputs[?OutputKey=='$OutputKey'].OutputValue | [0]" `
        --output text
}

function Get-StackStatus {
    param([string]$StackName)

    aws cloudformation describe-stacks `
        --stack-name $StackName `
        --region $Region `
        --query "Stacks[0].StackStatus" `
        --output text
}

foreach ($StackName in @($NetworkStackName, $SecurityStackName, $AppStackName)) {
    $Status = Get-StackStatus -StackName $StackName
    Write-Host "stack status: $StackName -> $Status"
    if ($Status -ne "CREATE_COMPLETE" -and $Status -ne "UPDATE_COMPLETE") {
        throw "Unexpected stack status for $StackName: $Status"
    }
}

$AlbDnsName = Get-StackOutput -StackName $AppStackName -OutputKey "AlbDnsName"
$TargetGroupArn = Get-StackOutput -StackName $AppStackName -OutputKey "TargetGroupArn"
$Ec2Az1InstanceId = Get-StackOutput -StackName $AppStackName -OutputKey "Ec2Az1InstanceId"
$Ec2Az2InstanceId = Get-StackOutput -StackName $AppStackName -OutputKey "Ec2Az2InstanceId"

if ([string]::IsNullOrWhiteSpace($AlbDnsName) -or $AlbDnsName -eq "None") {
    throw "AlbDnsName output was empty"
}

$ResponseBody = $null
$HttpStatus = $null

for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    try {
        $Response = Invoke-WebRequest -Uri ("http://{0}/" -f $AlbDnsName) -UseBasicParsing -TimeoutSec 10
        $ResponseBody = $Response.Content
        $HttpStatus = [int]$Response.StatusCode

        if ($HttpStatus -eq $ExpectedHttpStatus -and $ResponseBody -match "web-nginx|instance-id=|availability-zone=") {
            break
        }
    }
    catch {
    }

    Start-Sleep -Seconds 10
}

if ($HttpStatus -ne $ExpectedHttpStatus) {
    throw "Unexpected HTTP status from ALB: $HttpStatus"
}

if ($ResponseBody -notmatch "web-nginx|instance-id=|availability-zone=") {
    throw "Response body did not contain expected NGINX metadata"
}

$HealthyTargetCount = aws elbv2 describe-target-health `
    --target-group-arn $TargetGroupArn `
    --region $Region `
    --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" `
    --output text

if ([int]$HealthyTargetCount -ne $ExpectedHealthyTargets) {
    throw "Unexpected healthy target count: $HealthyTargetCount"
}

$PublicIpCount = aws ec2 describe-instances `
    --instance-ids $Ec2Az1InstanceId $Ec2Az2InstanceId `
    --region $Region `
    --query "length(Reservations[].Instances[?PublicIpAddress!=null][])" `
    --output text

if ([int]$PublicIpCount -ne 0) {
    throw "EC2 instances unexpectedly have public IPs: $PublicIpCount"
}

$AzValues = aws ec2 describe-instances `
    --instance-ids $Ec2Az1InstanceId $Ec2Az2InstanceId `
    --region $Region `
    --query "Reservations[].Instances[].Placement.AvailabilityZone" `
    --output text

$DistinctAzCount = (($AzValues -split "\s+") | Where-Object { $_ } | Sort-Object -Unique).Count

if ([int]$DistinctAzCount -ne 2) {
    throw "Instances are not distributed across two AZs: $DistinctAzCount"
}

$InstanceProfileCount = aws ec2 describe-instances `
    --instance-ids $Ec2Az1InstanceId $Ec2Az2InstanceId `
    --region $Region `
    --query "length(Reservations[].Instances[?IamInstanceProfile.Arn!=null][])" `
    --output text

if ([int]$InstanceProfileCount -ne 2) {
    throw "Missing IAM instance profile on one or more instances: $InstanceProfileCount"
}

Write-Host "Scenario test passed"
Write-Host "- HTTP status: $HttpStatus"
Write-Host "- Healthy targets: $HealthyTargetCount"
Write-Host "- Public IP count: $PublicIpCount"
Write-Host "- Distinct AZ count: $DistinctAzCount"
Write-Host "- IAM instance profile count: $InstanceProfileCount"