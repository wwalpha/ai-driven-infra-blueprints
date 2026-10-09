"""Terraform placement, composition, lexical safety and scoped regression fixtures."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_support.validator import MODULE, SCRIPT, project, write
from validation.terraform import blocks, root_directory, module_directory


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
        gate = {path.relative_to(root).as_posix()}

        def validate(scope=None, gate=None, wide=False, changed=(), task='infrastructure', initialized=False):
            validator = MODULE.Validator(root, scope, repository_wide_gate=wide)
            validator.accounts = accounts
            validator.template_mode = False
            validator.task_type = task
            validator.file_gate_paths = gate
            validator.changed_paths = set(changed)
            if initialized:
                validator.check_initialized_paths()
            validator.check_iac_selection()
            return validator

        def expect(name, validator, fails=False):
            assert bool(validator.errors) == fails, (name, validator.errors)
            cases.append(name)

        expect('T01', validate(initialized=True))
        shutil.rmtree(path.parent)
        expect('T02', validate(initialized=True), True)
        legacy = root / 'infra/terraform/environments/dev/cde/main.tf'
        legacy.parent.mkdir(parents=True)
        write(legacy, original)
        expect('T03', validate(initialized=True), True)
        path.parent.mkdir()
        write(path.parent / "terraform.tfvars", 'value = "dev-cde"\n')
        write(path, 'resource "aws_iam_role" "bad" {}\n')
        bad = validate()
        assert any('not Root' in error for error in bad.errors), bad.errors
        expect('T04', bad, True)
        shutil.rmtree(root / 'infra/terraform')
        write(path, original)

        unknown = root / 'infra/unknown/terraform/dev/main.tf'
        unknown.parent.mkdir(parents=True)
        write(unknown, original)
        expect('T05', validate(), True)
        assert not validate(scope, gate).errors
        assert validate(scope, {unknown.relative_to(root).as_posix()}).errors
        shutil.rmtree(root / 'infra/unknown')
        accounts[('dev', 'cde')]['engine'] = 'cloudformation'
        (root / 'infra/cloudformation/parameters/dev/cde').mkdir(parents=True)
        expect('T06', validate(), True)
        accounts[('dev', 'cde')]['engine'] = 'terraform'
        shutil.rmtree(root / 'infra/cloudformation')
        write(path, 'resource "aws_iam_role" "bad" {}\n')
        expect('T07', validate(), True)
        write(path, original)
        expect('T08', validate())
        write(path, original.replace('../modules/iam', '../modules/missing'))
        expect('T09', validate(), True)
        write(path, original)
        expect('T10', validate())
        alternate = root / 'infra/cde/terraform/modules/alternate'
        alternate.mkdir()
        write(unrelated, original.replace('../modules/iam', '../modules/alternate'))
        assert any('same source across environments' in error for error in validate().errors)
        assert validate(scope, gate).errors  # The same logical Module has a conflicting peer Root.
        assert validate(set(), {shared.relative_to(root).as_posix()},
                        changed={shared.relative_to(root).as_posix()}, task='governance').errors
        assert not validate({('dev', 'non-cde', 'ec2')}, set()).errors
        write(unrelated, original)
        alternate.rmdir()
        assert (path.parent / 'terraform.tfvars').read_text() != (unrelated.parent / 'terraform.tfvars').read_text()
        expect('T11', validate({('sandbox', '123456789012', 'ec2')}, initialized=True))
        accounts[('preview', 'ops')] = {'alias': 'ops', 'engine': 'cloudformation'}
        for directory in ('infra/cloudformation/parameters/preview/ops', 'docs/designs/preview/ops', 'model/preview/ops'):
            (root / directory).mkdir(parents=True)
        write(root / 'infra/cloudformation/parameters/preview/ops/example.json', '[]\n')
        expect('T12', validate(initialized=True))

        module_gate = {shared.relative_to(root).as_posix()}
        # Deleting a shared Module must check every Root referencing it, even in framework scope.
        saved_module = {p.name: p.read_text() for p in shared.parent.iterdir()}
        shutil.rmtree(shared.parent)
        expect('T13', validate(set(), module_gate, changed=module_gate, task='governance'), True)
        assert any('stg/main.tf' in error for error in validate(set(), module_gate, changed=module_gate, task='governance').errors)
        assert not validate(set(), module_gate, task='governance').errors
        shared.parent.mkdir()
        for name, text in saved_module.items():
            write(shared.parent / name, text)
        write(unrelated, original.replace('../modules/iam', '../modules/missing'))
        # An unrelated broken call must not become blocking because a different Module changed.
        assert not validate(set(), module_gate, changed=module_gate, task='governance').errors
        expect('T14', validate(scope, gate))
        assert validate(scope | {('stg', 'cde', 'ec2')}, gate).non_blocking_findings
        assert validate(scope | {('stg', 'cde', 'ec2')}, gate, True).errors
        assert validate(scope, {unrelated.relative_to(root).as_posix()}).errors
        write(unrelated, original)
        write(shared, 'module "child" { source = "../missing" }\n')
        assert validate(set(), module_gate, changed=module_gate, task='governance').errors
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
        expect('T15', validate(initialized=True))
        legacy.parent.mkdir(parents=True)
        write(legacy, original)
        expect('T16', validate(), True)
        shutil.rmtree(root / 'infra/terraform')
        write(path, original.replace('../modules/iam', '../../../non-cde/terraform/modules/iam'))
        expect('T17', validate(), True)
        write(path, original)

        # Normalized containment, not string prefix: .. and symlinks cannot cross targets.
        for source in ('../modules/iam/../iam', '../modules/./iam'):
            write(path, original.replace('../modules/iam', source))
            assert not validate().errors, validate().errors
        for source in ('../modules', '../modules/iam/../../stg', './copied',
                       '../modules/iam/../../../non-cde/terraform/modules/iam',
                       'registry.example/module', '${var.source}', '../modules/iam${var.suffix}'):
            write(path, original.replace('../modules/iam', source))
            assert validate().errors, source
        write(path, original)
        link = root / 'infra/cde/terraform/modules/other'
        link.symlink_to(root / 'infra/non-cde/terraform/modules/iam', target_is_directory=True)
        write(path, original.replace('../modules/iam', '../modules/other'))
        assert validate().errors
        link.unlink()
        write(path, original)
        module = shared.parent
        shutil.rmtree(module)
        module.symlink_to(root / 'infra/non-cde/terraform/modules/iam', target_is_directory=True)
        assert validate().errors
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
            assert validate().errors, relative
            extra.unlink()
        accounts[('dev', 'cde')]['engine'] = ''
        assert validate().errors
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
        assert not validate().errors, validate().errors
        assert [kind for kind, _, _ in blocks(path)] == ['module', 'variable', 'locals', 'data', 'output', 'resource']
        write(path, original.replace('module "application"', 'module application') + 'resource terraform_data valid { input = var.value }\n')
        assert not validate().errors
        write(path, 'resource aws_iam_role bad {}\n')
        assert any('not Root' in error for error in validate().errors)
        for invalid in ('/* unterminated', 'locals { text = <<EOF\nunterminated\n',
                        'locals { text = "unfinished', 'module "application" { source = "../modules/iam"'):
            write(path, invalid)
            assert any('cannot be read' in error for error in validate().errors)
        write(path, original)
        json_path = path.with_name('extra.tf.json')
        for body, fails in (({'resource': {'aws_iam_role': {'bad': {}}}}, True),
                            ({'resource': {'terraform_data': {'valid': {}}}}, False),
                            ({'module': {'extra': {'source': '../modules/missing'}}}, True),
                            ({'module': {'extra': {'source': '../modules/iam'}}}, False)):
            write(json_path, json.dumps(body))
            assert bool(validate().errors) == fails, body
        json_path.unlink()
        write(path, 'resource "awscc_iam_role" "bad" {}\n')
        assert validate().errors
        write(path, original)
        # Assets are not child Root configurations and remain valid in subdirectories.
        asset = path.parent / 'templates/user-data.sh'
        asset.parent.mkdir()
        write(asset, '#!/bin/sh\n')
        assert not validate().errors
        # Nested local Modules and remote child Modules retain Terraform functionality.
        child = module.parent / 'child'
        child.mkdir()
        write(child / 'main.tf', 'resource "aws_iam_role" "child" {}\n')
        write(shared, 'module "child" { source = "../child" }\nmodule "remote" { source = "hashicorp/consul/aws" }\n')
        assert not validate().errors
        write(shared, 'module "child" { source = "' + str(root / 'infra/non-cde/terraform/modules/iam') + '" }\n')
        assert validate().errors
        write(shared, 'module "child" { source = "../../stg" }\n')
        assert validate().errors
        write(shared, 'resource "aws_iam_role" "example" {}\n')
        cache = path.parent / '.terraform/modules/foreign/main.tf'
        cache.parent.mkdir(parents=True)
        write(cache, 'resource "aws_iam_role" "cached" {}\n')
        assert not validate().errors
        empty = root / 'infra/cde/terraform/preview'
        empty.mkdir()
        accounts[('preview', 'cde')] = {'alias': 'cde', 'engine': 'terraform'}
        assert not validate({('preview', 'cde', 'ec2')}).errors
        # Terraform is optional before implementation and in CloudFormation-only consumers.
        for directory in ('cde', 'non-cde', '123456789012'):
            shutil.rmtree(root / 'infra' / directory)
        for values in accounts.values():
            values['engine'] = 'cloudformation'
        assert not validate().errors
        for values in accounts.values():
            values['engine'] = 'terraform'
        shutil.rmtree(root / 'infra/cloudformation')
        assert not validate().errors

    # Alias names must not gain new restrictions from the target-first layout.
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

    # Existing optional CLI regression stays here; no CLI dispatch added to the task loop.
    terraform = shutil.which('terraform')
    if terraform:
        with project() as root, tempfile.TemporaryDirectory() as data:
            module = root / 'infra/system/terraform/modules/example'
            module.mkdir(parents=True)
            write(module / 'variables.tf', 'variable "value" { type = string }\n')
            write(module / 'main.tf', 'resource "terraform_data" "example" { input = var.value }\n')
            for env in ('dev', 'stg'):
                directory = root / f'infra/system/terraform/{env}'
                directory.mkdir(parents=True)
                write(directory / 'main.tf', 'module "application" {\n  source = "../modules/example"\n  value = var.value\n}\nvariable "value" { type = string }\n')
                write(directory / 'terraform.tfvars', f'value = "{env}"\n')
                for args in (['fmt'], ['fmt', '-check'], ['init', '-backend=false', '-input=false'], ['validate']):
                    result = subprocess.run([terraform, *args], cwd=directory, capture_output=True, text=True,
                                            env={**os.environ, 'TF_DATA_DIR': str(Path(data) / env), 'CHECKPOINT_DISABLE': '1'})
                    assert result.returncode == 0, result.stdout + result.stderr
            result = subprocess.run([terraform, 'fmt', '-check', '-recursive', str(root)], capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert not list(root.rglob('*.tfstate')) and not list(root.rglob('*.tfplan'))
    assert cases == [f'T{i:02}' for i in range(1, 18)], cases
    print('Terraform paths: 17/17 PASS (T01-T17, plus lexical/JSON, normalized sources, nested Modules and scope regressions; fmt/init/validate ' + ('PASS' if terraform else 'not installed') + ')')
