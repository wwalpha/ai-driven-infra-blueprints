# IAM Resource Naming Rules

共通の適用範囲・除外・Name tag policy・component規則は[共通ルール](../aws-resource-naming.md)に従う。

## Naming patterns

| AWS service | AWS resource | Catalog resource types | Naming target | Pattern |
| --- | --- | --- | --- | --- |
| AWS IAM | Role | `IAM.Role` | `RoleName` | `{{application}}-{{environment}}-{{purpose}}Role[-{{suffix}}]` |

## Service-specific constraints

- RoleNameの`purpose`はhuman-confirmedなPascalCaseの用途名（例：`DataManagement`）とし、直後に固定の`Role`を付ける。このcomponentは共通のlower-kebab-case規則の例外とし、`application`、`environment`、`suffix`は共通ルールを維持する。`target_alias`（例：`cde`）を自動挿入しない。
- `suffix`は任意とし、選択targetの`project.json`に設定されている場合だけ末尾へ`-<suffix>`を付ける。未設定ならハイフンごと省略する。例：`venusinf-dev-DataManagementRole`／`venusinf-dev-DataManagementRole-aaaaaa`。
- AWS IAM Roleは64文字以内、customer managed policyは128文字以内とし、caseだけが異なる名前を作らない。
