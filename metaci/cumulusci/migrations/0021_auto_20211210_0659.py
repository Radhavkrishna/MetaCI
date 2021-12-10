# Generated by Django 3.1.13 on 2021-12-10 06:59

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('plan', '0041_auto_20211208_1840'),
        ('cumulusci', '0020_auto_20211210_0359'),
    ]

    operations = [
        migrations.AlterField(
            model_name='orgpool',
            name='org_shape',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='org_pools', to='cumulusci.org'),
        ),
        migrations.AlterField(
            model_name='orgpool',
            name='plan',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='org_pools', to='plan.plan'),
        ),
    ]