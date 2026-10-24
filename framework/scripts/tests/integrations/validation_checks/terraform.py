"""Terraform placement, composition, lexical safety and scoped regression fixtures."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from support.it_case_receipt import it_case
from support.validator import project as project
from support.validator import write as write
from validation.terraform import module_directory as module_directory


@it_case
def check_cli():
    terraform = shutil.which('terraform')

    if not terraform:
        raise RuntimeError('Terraform CLI unavailable: integration verification did not run')
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
