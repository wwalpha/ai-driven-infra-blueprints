"""glue comparison contracts and projections."""

REF_ATTRIBUTES = {'Glue.Connection': 'Name', 'Glue.SecurityConfiguration': 'Name'}

KMS_FORMS = {'Glue.SecurityConfiguration.EncryptionConfiguration.S3Encryptions[].KmsKeyArn': {'AliasArn'}, 'Glue.SecurityConfiguration.EncryptionConfiguration.CloudWatchEncryption.KmsKeyArn': {'AliasArn'}}
