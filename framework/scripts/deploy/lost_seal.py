"""Explicit Human exception for lost reset seals; original bytes remain untrusted."""

import json
import sys
from datetime import datetime, timezone

from utils.cloudformation.inputs import Blocked
from utils.json_format import fingerprint
from utils.sealed_evidence import sealed

from deploy import operation_journal as J
from deploy import operation_reset as R

WARNING = (
    "Historical signatures cannot be verified. Original scope and pending operations "
    "may be unknown. Only the listed future Stacks are released; duplicate execution "
    "and dependency risks are accepted by the Human, not machine-verified."
)


def inventory(journal):
    folder = journal.parent / "resets"
    J.private_path(folder, directory=True)
    result = R.fence_inventory(folder)
    if not result:
        raise Blocked("lost-key recovery requires retained reset archives")
    return result


def snapshot(root, environment, account, alias, stacks, risk, aws):
    target, journal, project_sha = R.select(root, environment, account, alias)
    names = sorted(stacks)
    if (
        not names
        or len(set(names)) != len(names)
        or any(not R.STACK_NAME.fullmatch(n) for n in names)
        or not risk.strip()
    ):
        raise Blocked("lost-key recovery requires exact StackNames and explicit risk")
    if journal.exists():
        raise Blocked("settle the active operation journal before lost-key recovery")
    frozen = inventory(journal)
    observations = [R.inspect_aws(aws, target, n, []) for n in names]
    for item in observations:
        status = item["stackStatus"]
        if status != "ABSENT" and status not in R.COMPLETE:
            raise Blocked(
                "lost-key recovery requires absent or successful Stacks: "
                + item["stack"]
            )
    if frozen != inventory(journal):
        raise Blocked("lost-key archive changed during AWS inspection")
    value = dict(
        version=1,
        kind="lost-key",
        repository=str(root),
        environment=environment,
        account=account,
        alias=alias,
        target=target,
        projectSha256=project_sha,
        journal=str(journal),
        archives=frozen,
        stacks=names,
        aws=observations,
        residualRisk=risk,
        warning=WARNING,
    )
    value["id"] = fingerprint(value)
    return value


def challenge(value):
    account, region = J.target_identity(value["target"])
    return (
        f"ACCEPT-LOST-KEY {account} {region} {','.join(value['stacks'])} {value['id']}"
    )


def confirm(value):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise Blocked("Lost-key Apply requires a human-operated interactive console")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    print(
        "Only the Human may accept lost-evidence risk; an LLM must never enter approval."
    )
    try:
        entered = input(
            "Confirm the entire Plan by typing:\n" + challenge(value) + "\n> "
        )
    except EOFError as error:
        raise Blocked("Human lost-key approval cancelled") from error
    if entered != challenge(value):
        raise Blocked("explicit Human lost-key approval does not match the Plan")
    return dict(
        method="interactive-console",
        challenge=entered,
        time=datetime.now(timezone.utc).isoformat(),
    )


def current_snapshot(args, root, aws, value):
    return snapshot(
        root,
        args.environment,
        args.aws_account_id,
        args.alias,
        value["stacks"],
        value["residualRisk"],
        aws,
    )


def run(args, root, aws):
    _, journal, _ = R.select(root, args.environment, args.aws_account_id, args.alias)
    with J.locked(journal):
        if args.action == "lost-key-plan":
            if args.plan or not args.stack or not args.risk:
                raise Blocked(
                    "lost-key-plan requires --stack and --risk, accepts no --plan"
                )
            value = snapshot(
                root,
                args.environment,
                args.aws_account_id,
                args.alias,
                args.stack,
                args.risk,
                aws,
            )
            folder = R.directory(journal.parent / "lost-key-plans")
            R.save_once(
                folder / (value["id"] + ".json"), sealed(journal.parent, value).encode()
            )
            return value
        if (
            not args.plan
            or not R.IDENTIFIER.fullmatch(args.plan)
            or args.stack
            or args.risk
        ):
            raise Blocked("lost-key-apply requires only --plan")
        value = R.signed_document(
            journal, journal.parent / "lost-key-plans" / (args.plan + ".json")
        )
        R.verify_plan(value, args.plan)
        if value.get("kind") != "lost-key":
            raise Blocked("not a lost-key Plan")

        if value != current_snapshot(args, root, aws, value):
            raise Blocked("lost-key Plan target, archives or AWS changed")
        approval = confirm(value)
        if value != current_snapshot(args, root, aws, value):
            raise Blocked("lost-key Plan changed during Human approval")
        folder = R.directory(journal.parent / "lost-key-approvals")
        R.save_once(
            folder / (args.plan + ".json"),
            sealed(
                journal.parent,
                dict(plan=value, approval=approval, status="HUMAN_ACCEPTED_LOST_KEY"),
            ).encode(),
        )
        return dict(
            status="HUMAN_ACCEPTED_LOST_KEY", plan=args.plan, stacks=value["stacks"]
        )


def approved(journal, backend, scope):
    folder = journal.parent / "lost-key-approvals"
    if not folder.exists():
        return False
    J.private_path(folder, directory=True)
    # Validate every receipt, including its frozen archives, before trusting any scope.
    permits = []
    for path in sorted(folder.iterdir()):
        item = R.signed_document(journal, path)
        plan = item["plan"]
        R.verify_plan(plan, path.stem)
        if (
            plan.get("kind") != "lost-key"
            or path.name != plan["id"] + ".json"
            or item.get("status") != "HUMAN_ACCEPTED_LOST_KEY"
            or item["approval"].get("method") != "interactive-console"
            or item["approval"].get("challenge") != challenge(plan)
            or plan["journal"] != str(journal)
            or plan["archives"] != inventory(journal)
        ):
            raise Blocked("lost-key approval or retained archives changed")
        permits.append(plan)
    for plan in permits:
        if (
            plan["target"] == backend.target
            and plan["repository"] == str(backend.root)
            and plan["environment"] == backend.environment
            and set(scope) <= set(plan["stacks"])
            and plan["projectSha256"]
            == R.digest((backend.root / "project.json").read_bytes())
        ):
            return True
    return False
