"""Terraform composition, lexical safety and scoped regression fixtures."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_support.validator import MODULE, SCRIPT, project, write
from validation.terraform import blocks


def check_configuration():
    with project() as root:
        modules = root / 'infra/terraform/modules'
        for alias in ('', 'cde', 'non-cde'):
            directory = modules / alias
            directory.mkdir(parents=True, exist_ok=True)
            write(directory / 'main.tf', 'resource "terraform_data" "example" { input = var.value }\n')
            write(directory / 'variables.tf', 'variable "value" { type = string }\n')
        accounts = {(env, alias): {'alias': alias, 'engine': 'terraform'}
                    for env in ('dev', 'stg') for alias in ('cde', 'non-cde')}
        accounts[('sandbox', '123456789012')] = {'alias': '', 'engine': 'terraform'}
        paths = {}
        for (env, target), values in accounts.items():
            directory = root / f'infra/terraform/environments/{env}/{target}'
            directory.mkdir(parents=True)
            source = '../../../modules' + ('/' + values['alias'] if values['alias'] else '')
            paths[(env, target)] = directory / 'main.tf'
            write(directory / 'main.tf', f'module "application" {{\n  source = "{source}"\n  value = var.value\n}}\nvariable "value" {{ type = string }}\n')
            write(directory / 'terraform.tfvars', f'value = "{env}-{target}"\n')
            write(directory / 'backend.tf', f'terraform {{ backend "local" {{ path = "{env}-{target}.tfstate" }} }}\n')

        def validate(scope=None, gate=None, wide=False):
            validator = MODULE.Validator(root, scope, repository_wide_gate=wide)
            validator.accounts = accounts
            validator.template_mode = False
            validator.task_type = 'infrastructure'
            validator.file_gate_paths = gate
            validator.check_iac_selection()
            return validator

        assert not validate().errors  # Same Alias shared; different Aliases split; Account ID compatible.
        assert (paths[('dev', 'cde')].parent / 'terraform.tfvars').read_text() != \
               (paths[('stg', 'cde')].parent / 'terraform.tfvars').read_text()
        path = paths[('dev', 'cde')]
        original = path.read_text()
        normalized = original.replace('../../../modules/cde', '../../../modules/non-cde/../cde')
        write(path, normalized)
        assert not validate().errors
        for source in ('../../../modules/non-cde', '../../../modules', '../../../modules/missing',
                       './missing', 'registry.example/module', '${var.source}'):
            write(path, original.replace('../../../modules/cde', source))
            assert validate().errors, source
        write(path, original + 'resource "terraform_data" "root" {}\n')
        assert any('not Root' in error for error in validate().errors)
        write(path, original + '''# resource "fake" "comment" {}
/* module "fake" { source = "./missing" } */
locals {
  text = "resource \\"fake\\" \\"string\\" {}"
  nested = "${format("%s", "resource fake string {}")}"
  script = <<-EOF
    resource "fake" "heredoc" {}
    module "fake" { source = "./missing" }
    EOF
}
''')
        assert not validate().errors, validate().errors
        assert [kind for kind, _, _ in blocks(path)] == ['module', 'variable', 'locals']
        for invalid in ('/* unterminated', 'locals { text = <<EOF\nunterminated\n', 'locals { text = "unfinished',
                        'module "application" { source = "../../../modules/cde"'):
            write(path, invalid)
            assert any('cannot be read' in error for error in validate().errors)
        write(path, original)
        json_path = path.with_name('extra.tf.json')
        write(json_path, json.dumps({'resource': {'terraform_data': {'bad': {}}}}))
        assert any('not Root' in error for error in validate().errors)
        write(json_path, json.dumps({'module': {'extra': {'source': '../../../modules/non-cde'}}}))
        assert validate().errors
        write(json_path, json.dumps({'module': {'extra': {'source': '../../../modules/cde'}}}))
        assert not validate().errors
        json_path.unlink()
        link = path.parent / 'wrong-alias'
        link.symlink_to(modules / 'non-cde', target_is_directory=True)
        write(path, original.replace('../../../modules/cde', './wrong-alias'))
        assert validate().errors
        link.unlink()
        write(path, original)
        shutil.rmtree(modules / 'cde')
        (modules / 'cde').symlink_to(modules / 'non-cde', target_is_directory=True)
        assert validate().errors  # Alias-directory symlinks must not collapse Aliases.
        (modules / 'cde').unlink()
        (modules / 'cde').mkdir()
        write(modules / 'cde/main.tf', 'resource "terraform_data" "example" {}\n')

        unrelated = paths[('stg', 'cde')]
        write(unrelated, 'resource "terraform_data" "root" {}\n')
        scope = {('dev', 'cde', 'ec2')}
        gate = {path.relative_to(root).as_posix()}
        assert not validate(scope, gate).errors
        assert validate(scope | {('stg', 'cde', 'ec2')}, gate).non_blocking_findings
        assert validate(scope | {('stg', 'cde', 'ec2')}, gate, True).errors
        assert validate(scope, {unrelated.relative_to(root).as_posix()}).errors
        write(unrelated, original)
        unknown = root / 'infra/terraform/environments/dev/unknown/main.tf'
        unknown.parent.mkdir(parents=True)
        write(unknown, original)
        assert any('target is not defined' in error for error in validate().errors)
        assert not validate(scope, gate).errors
        assert validate(scope, {unknown.relative_to(root).as_posix()}).errors
        unknown.unlink()
        accounts[('dev', 'cde')]['engine'] = 'cloudformation'
        (root / 'infra/cloudformation').mkdir()
        assert any('Terraform is not selected' in error for error in validate().errors)
        accounts[('dev', 'cde')]['engine'] = 'terraform'
        (root / 'infra/cloudformation').rmdir()
        # No generated files is valid before implementation; cached init files are ignored.
        empty = root / 'infra/terraform/environments/new/cde'
        empty.mkdir(parents=True)
        accounts[('new', 'cde')] = {'alias': 'cde', 'engine': 'terraform'}
        cache = path.parent / '.terraform/modules/foreign/main.tf'
        cache.parent.mkdir(parents=True)
        write(cache, 'resource "terraform_data" "cached" {}\n')
        assert not validate().errors
        assert not validate({('new', 'cde', 'ec2')}).errors
        # Terraform is optional in CloudFormation-only consumers.
        shutil.rmtree(root / 'infra/terraform')
        (root / 'infra/cloudformation').mkdir()
        for values in accounts.values():
            values['engine'] = 'cloudformation'
        assert not validate().errors
        for values in accounts.values():
            values['engine'] = 'terraform'
        (root / 'infra/cloudformation').rmdir()
        assert not validate().errors  # Not-yet-generated Terraform directory.

    # Real fmt/init/validate on provider-free configurations, with isolated data and no state/plan.
    terraform = shutil.which('terraform')
    if terraform:
        with project() as root, tempfile.TemporaryDirectory() as data:
            module = root / 'modules/cde'
            module.mkdir(parents=True)
            write(module / 'variables.tf', 'variable "value" { type = string }\n')
            write(module / 'main.tf', 'resource "terraform_data" "example" { input = var.value }\n')
            for env in ('dev', 'stg'):
                directory = root / f'environments/{env}/cde'
                directory.mkdir(parents=True)
                write(directory / 'main.tf', 'module "application" {\n  source = "../../../modules/cde"\n  value = var.value\n}\nvariable "value" { type = string }\n')
                write(directory / 'terraform.tfvars', f'value = "{env}"\n')
                for args in (['fmt'], ['fmt', '-check'], ['init', '-backend=false', '-input=false'], ['validate']):
                    result = subprocess.run([terraform, *args], cwd=directory, capture_output=True, text=True,
                                            env={**os.environ, 'TF_DATA_DIR': str(Path(data) / env), 'CHECKPOINT_DISABLE': '1'})
                    assert result.returncode == 0, result.stdout + result.stderr
            result = subprocess.run([terraform, 'fmt', '-check', '-recursive', str(root)], capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert not list(root.rglob('*.tfstate')) and not list(root.rglob('*.tfplan'))
    print('Terraform composition: PASS (Alias sharing/separation, parameters, Root resources, normalized paths, Account ID, scope/file gates, ungenerated files, HCL/JSON; fmt/init/validate ' + ('PASS' if terraform else 'not installed') + ')')
