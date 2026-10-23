"""Terraform placement, composition, lexical safety and scoped regression fixtures."""

import json
import shutil
from functools import partial as _bind_framework_callback

from support.validator import MODULE, SCRIPT, project, write
from validation.terraform import blocks, module_directory, root_directory


def _callback_check_configuration_expect(cases, /, name, validator, fails=False):
    assert bool(validator.errors) == fails, (name, validator.errors)
    cases.append(name)


def _callback_check_configuration_validate(accounts, root, /, scope=None, changed=(), task='infrastructure', initialized=False):
    validator = MODULE.Validator(root, scope)
    validator.accounts = accounts
    validator.template_mode = False
    validator.task_type = task
    validator.changed_paths = set(changed)
    if initialized:
        validator.check_initialized_paths()
    validator.check_iac_selection()
    return validator


def check_configuration():
    cases = []
    with project() as root:
        accounts = {(env, alias): {'alias': alias, 'engine': 'terraform'}
                    for env in ('dev', 'stg') for alias in ('cde', 'non-cde')}
        accounts[('sandbox', '123456789012')] = {'alias': '', 'engine': 'terraform'}
        original = 'module "application" {\n  source = "../modules/iam"\n  value = var.value\n}\nvariable "value" { type = string }\n'
        for env, target in accounts:
            for directory in (f'docs/designs/{env}/{target}', f'model/{env}/{target}',
                              f'infra/{target}/terraform/{env}', f'infra/{target}/terraform/modules/iam'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            directory = root / f'infra/{target}/terraform/{env}'
            assert root_directory(root, (env, target)) == directory
            write(directory / 'main.tf', original)
            write(directory / 'terraform.tfvars', f'value = "{env}-{target}"\n')
            module = root / f'infra/{target}/terraform/modules/iam'
            assert module_directory(root, target) == module.parent
            write(module / 'main.tf', 'resource "aws_iam_role" "example" {}\n')
            write(module / 'variables.tf', 'variable "value" { type = string }\n')
        path = root / 'infra/cde/terraform/dev/main.tf'
        shared = root / 'infra/cde/terraform/modules/iam/main.tf'
        unrelated = root / 'infra/cde/terraform/stg/main.tf'
        scope = {('dev', 'cde', 'ec2')}


        expect = _bind_framework_callback(_callback_check_configuration_expect, cases)

        expect('T01', _callback_check_configuration_validate(accounts, root, initialized=True))
        shutil.rmtree(path.parent)
        expect('T02', _callback_check_configuration_validate(accounts, root, initialized=True), True)
        legacy = root / 'infra/terraform/environments/dev/cde/main.tf'
        legacy.parent.mkdir(parents=True)
        write(legacy, original)
        expect('T03', _callback_check_configuration_validate(accounts, root, initialized=True), True)
        path.parent.mkdir()
        write(path.parent / "terraform.tfvars", 'value = "dev-cde"\n')
        write(path, 'resource "aws_iam_role" "bad" {}\n')
        bad = _callback_check_configuration_validate(accounts, root)
        assert any('not Root' in error for error in bad.errors), bad.errors
        expect('T04', bad, True)
        shutil.rmtree(root / 'infra/terraform')
        write(path, original)

        unknown = root / 'infra/unknown/terraform/dev/main.tf'
        unknown.parent.mkdir(parents=True)
        write(unknown, original)
        expect('T05', _callback_check_configuration_validate(accounts, root), True)
        assert not _callback_check_configuration_validate(accounts, root, scope).errors
        shutil.rmtree(root / 'infra/unknown')
        accounts[('dev', 'cde')]['engine'] = 'cloudformation'
        (root / 'infra/cloudformation/parameters/dev/cde').mkdir(parents=True)
        expect('T06', _callback_check_configuration_validate(accounts, root), True)
        accounts[('dev', 'cde')]['engine'] = 'terraform'
        shutil.rmtree(root / 'infra/cloudformation')
        write(path, 'resource "aws_iam_role" "bad" {}\n')
        expect('T07', _callback_check_configuration_validate(accounts, root), True)
        write(path, original)
        expect('T08', _callback_check_configuration_validate(accounts, root))
        write(path, original.replace('../modules/iam', '../modules/missing'))
        expect('T09', _callback_check_configuration_validate(accounts, root), True)
        write(path, original)
        expect('T10', _callback_check_configuration_validate(accounts, root))
        alternate = root / 'infra/cde/terraform/modules/alternate'
        alternate.mkdir()
        write(unrelated, original.replace('../modules/iam', '../modules/alternate'))
        assert any('same source across environments' in error for error in _callback_check_configuration_validate(accounts, root).errors)
        assert _callback_check_configuration_validate(accounts, root, scope).errors  # The same logical Module has a conflicting peer Root.
        assert _callback_check_configuration_validate(accounts, root, set(),
                        changed={shared.relative_to(root).as_posix()}, task='governance').errors
        assert not _callback_check_configuration_validate(accounts, root, {('dev', 'non-cde', 'ec2')}).errors
        write(unrelated, original)
        alternate.rmdir()
        assert (path.parent / 'terraform.tfvars').read_text() != (unrelated.parent / 'terraform.tfvars').read_text()
        expect('T11', _callback_check_configuration_validate(accounts, root, {('sandbox', '123456789012', 'ec2')}, initialized=True))
        accounts[('preview', 'ops')] = {'alias': 'ops', 'engine': 'cloudformation'}
        for directory in ('infra/cloudformation/parameters/preview/ops', 'docs/designs/preview/ops', 'model/preview/ops'):
            (root / directory).mkdir(parents=True)
        write(root / 'infra/cloudformation/parameters/preview/ops/example.json', '[]\n')
        expect('T12', _callback_check_configuration_validate(accounts, root, initialized=True))

        module_changes = {shared.relative_to(root).as_posix()}
        # Deleting a shared Module must check every Root referencing it, even in framework scope.
        saved_module = {p.name: p.read_text() for p in shared.parent.iterdir()}
        shutil.rmtree(shared.parent)
        expect('T13', _callback_check_configuration_validate(accounts, root, set(), changed=module_changes, task='governance'), True)
        assert any('stg/main.tf' in error for error in _callback_check_configuration_validate(accounts, root, set(), changed=module_changes, task='governance').errors)
        assert not _callback_check_configuration_validate(accounts, root, set(), task='governance').errors
        shared.parent.mkdir()
        for name, text in saved_module.items():
            write(shared.parent / name, text)
        write(unrelated, original.replace('../modules/iam', '../modules/missing'))
        # Changed shared Modules retain validation of the target Root configurations.
        assert any("source does not exist" in error for error in
                   _callback_check_configuration_validate(accounts, root, set(), changed=module_changes, task='governance').errors)
        expect('T14', _callback_check_configuration_validate(accounts, root, scope))
        assert _callback_check_configuration_validate(accounts, root, scope | {('stg', 'cde', 'ec2')}).errors
        write(unrelated, original)
        write(shared, 'module "child" { source = "../missing" }\n')
        assert _callback_check_configuration_validate(accounts, root, set(), changed=module_changes, task='governance').errors
        write(shared, 'resource "aws_iam_role" "example" {}\n')

        # Initialization/add-target are agent prompts, not executable scaffold commands.
        # Exercise their absent-only directory step twice and check their rerun guards.
        snapshot = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        for _ in range(2):
            for target in accounts:
                if accounts[target]['engine'] == 'terraform':
                    root_directory(root, target).mkdir(parents=True, exist_ok=True)
        assert snapshot == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        for name in ('01_initialize.md', '02_add-target.md'):
            prompt = (SCRIPT.parents[2] / 'framework/prompts/codex' / name).read_text()
            assert 'infra/<target-directory>/terraform/<environment>/.gitkeep' in prompt
            assert 'do not create per-environment copies' in prompt
            if name == '01_initialize.md':
                assert 'If `project.json` already exists, treat the repository as initialized. Stop without changing files' in prompt
            else:
                assert 'The target-directory alias or AWS account ID does not exist in the same environment' in prompt
                assert 'Stop without changes for missing, invalid, duplicate, or contradictory values.' in prompt
        expect('T15', _callback_check_configuration_validate(accounts, root, initialized=True))
        legacy.parent.mkdir(parents=True)
        write(legacy, original)
        expect('T16', _callback_check_configuration_validate(accounts, root), True)
        shutil.rmtree(root / 'infra/terraform')
        write(path, original.replace('../modules/iam', '../../../non-cde/terraform/modules/iam'))
        expect('T17', _callback_check_configuration_validate(accounts, root), True)
        write(path, original)

        # Normalized containment, not string prefix: .. and symlinks cannot cross targets.
        for source in ('../modules/iam/../iam', '../modules/./iam'):
            write(path, original.replace('../modules/iam', source))
            assert not _callback_check_configuration_validate(accounts, root).errors, _callback_check_configuration_validate(accounts, root).errors
        for source in ('../modules', '../modules/iam/../../stg', './copied',
                       '../modules/iam/../../../non-cde/terraform/modules/iam',
                       'registry.example/module', '${var.source}', '../modules/iam${var.suffix}'):
            write(path, original.replace('../modules/iam', source))
            assert _callback_check_configuration_validate(accounts, root).errors, source
        write(path, original)
        link = root / 'infra/cde/terraform/modules/other'
        link.symlink_to(root / 'infra/non-cde/terraform/modules/iam', target_is_directory=True)
        write(path, original.replace('../modules/iam', '../modules/other'))
        assert _callback_check_configuration_validate(accounts, root).errors
        link.unlink()
        write(path, original)
        module = shared.parent
        shutil.rmtree(module)
        module.symlink_to(root / 'infra/non-cde/terraform/modules/iam', target_is_directory=True)
        assert _callback_check_configuration_validate(accounts, root).errors
        module.unlink()
        module.mkdir()
        write(shared, 'resource "aws_iam_role" "example" {}\n')

        # Invalid engines, undefined environments and misplaced Root/Module files all fail.
        for relative in ('infra/cde/terraform/qa/main.tf', 'infra/cde/terraform/dev/copied/main.tf',
                         'infra/cde/terraform/modules/main.tf', 'infra/cde/terraform/main.tf',
                         'infra/cde/main.tf', 'infra/terraform/modules/cde/main.tf',
                         'infra/unknown/terraform/modules/iam/main.tf'):
            extra = root / relative
            extra.parent.mkdir(parents=True, exist_ok=True)
            write(extra, 'resource "aws_iam_role" "bad" {}\n')
            assert _callback_check_configuration_validate(accounts, root).errors, relative
            extra.unlink()
        accounts[('dev', 'cde')]['engine'] = ''
        assert _callback_check_configuration_validate(accounts, root).errors
        accounts[('dev', 'cde')]['engine'] = 'terraform'
        write(path, original + '''# resource "aws_fake" "comment" {}
/* module "fake" { source = "./missing" } */
locals {
  text = "resource \\"aws_fake\\" \\"string\\" {}"
  nested = "${format("%s", "resource fake string {}")}"
  script = <<-EOF
    resource "aws_fake" "heredoc" {}
    module "fake" { source = "./missing" }
    EOF
}
data "aws_region" "current" {}
output "value" { value = var.value }
resource "terraform_data" "valid" { input = var.value }
''')
        assert not _callback_check_configuration_validate(accounts, root).errors, _callback_check_configuration_validate(accounts, root).errors
        assert [kind for kind, _, _ in blocks(path)] == ['module', 'variable', 'locals', 'data', 'output', 'resource']
        write(path, original.replace('module "application"', 'module application') + 'resource terraform_data valid { input = var.value }\n')
        assert not _callback_check_configuration_validate(accounts, root).errors
        write(path, 'resource aws_iam_role bad {}\n')
        assert any('not Root' in error for error in _callback_check_configuration_validate(accounts, root).errors)
        for invalid in ('/* unterminated', 'locals { text = <<EOF\nunterminated\n',
                        'locals { text = "unfinished', 'module "application" { source = "../modules/iam"'):
            write(path, invalid)
            assert any('cannot be read' in error for error in _callback_check_configuration_validate(accounts, root).errors)
        write(path, original)
        json_path = path.with_name('extra.tf.json')
        for body, fails in (({'resource': {'aws_iam_role': {'bad': {}}}}, True),
                            ({'resource': {'terraform_data': {'valid': {}}}}, False),
                            ({'module': {'extra': {'source': '../modules/missing'}}}, True),
                            ({'module': {'extra': {'source': '../modules/iam'}}}, False)):
            write(json_path, json.dumps(body))
            assert bool(_callback_check_configuration_validate(accounts, root).errors) == fails, body
        json_path.unlink()
        write(path, 'resource "awscc_iam_role" "bad" {}\n')
        assert _callback_check_configuration_validate(accounts, root).errors
        write(path, original)
        # Assets are not child Root configurations and remain valid in subdirectories.
        asset = path.parent / 'templates/user-data.sh'
        asset.parent.mkdir()
        write(asset, '#!/bin/sh\n')
        assert not _callback_check_configuration_validate(accounts, root).errors
        # Nested local Modules and remote child Modules retain Terraform functionality.
        child = module.parent / 'child'
        child.mkdir()
        write(child / 'main.tf', 'resource "aws_iam_role" "child" {}\n')
        write(shared, 'module "child" { source = "../child" }\nmodule "remote" { source = "hashicorp/consul/aws" }\n')
        assert not _callback_check_configuration_validate(accounts, root).errors
        write(shared, 'module "child" { source = "' + str(root / 'infra/non-cde/terraform/modules/iam') + '" }\n')
        assert _callback_check_configuration_validate(accounts, root).errors
        write(shared, 'module "child" { source = "../../stg" }\n')
        assert _callback_check_configuration_validate(accounts, root).errors
        write(shared, 'resource "aws_iam_role" "example" {}\n')
        cache = path.parent / '.terraform/modules/foreign/main.tf'
        cache.parent.mkdir(parents=True)
        write(cache, 'resource "aws_iam_role" "cached" {}\n')
        assert not _callback_check_configuration_validate(accounts, root).errors
        empty = root / 'infra/cde/terraform/preview'
        empty.mkdir()
        accounts[('preview', 'cde')] = {'alias': 'cde', 'engine': 'terraform'}
        assert not _callback_check_configuration_validate(accounts, root, {('preview', 'cde', 'ec2')}).errors
        # Terraform is optional before implementation and in CloudFormation-only consumers.
        for directory in ('cde', 'non-cde', '123456789012'):
            shutil.rmtree(root / 'infra' / directory)
        for values in accounts.values():
            values['engine'] = 'cloudformation'
        assert not _callback_check_configuration_validate(accounts, root).errors
        for values in accounts.values():
            values['engine'] = 'terraform'
        shutil.rmtree(root / 'infra/cloudformation')
        assert not _callback_check_configuration_validate(accounts, root).errors
    for alias in ('cloudformation', 'terraform'):
        with project() as root:
            directory = root / f'infra/{alias}/terraform/custom-environment'
            directory.mkdir(parents=True)
            write(directory / 'main.tf', 'locals { value = 1 }\n')
            validator = MODULE.Validator(root)
            validator.template_mode = False
            validator.accounts = {('custom-environment', alias): {'alias': alias, 'engine': 'terraform'}}
            validator.check_iac_selection()
            assert not validator.errors, validator.errors
    assert cases == [f'T{i:02}' for i in range(1, 18)], cases
    print("Terraform validator inputs: PASS")
