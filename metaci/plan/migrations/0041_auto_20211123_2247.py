# Generated by Django 3.1.13 on 2021-11-23 22:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plan', '0040_plan_commit_status_regex'),
    ]

    operations = [
        migrations.AlterField(
            model_name='plan',
            name='role',
            field=models.CharField(choices=[('beta_release', 'Beta Release'), ('beta_test', 'Beta Test'), ('deploy', 'Deployment'), ('feature', 'Feature Test'), ('feature_robot', 'Feature Test Robot'), ('publish_installer', 'Publish Installer'), ('other', 'Other'), ('push_sandbox', 'Push Sandbox'), ('push_production', 'Push Production'), ('qa', 'QA Org'), ('release_deploy', 'Release Deploy'), ('release', 'Release'), ('release_test', 'Release Test'), ('scratch', 'Scratch Org')], max_length=17),
        ),
    ]
