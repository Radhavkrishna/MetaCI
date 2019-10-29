# Generated by Django 2.1.3 on 2018-12-07 20:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testresults", "0008_merge_20180911_1915"),
    ]

    operations = [
        migrations.AlterField(
            model_name="testclass",
            name="test_type",
            field=models.CharField(
                choices=[
                    ("Apex", "Apex"),
                    ("JUnit", "JUnit"),
                    ("Robot", "Robot"),
                    ("Other", "Other"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="testresult",
            name="outcome",
            field=models.CharField(
                choices=[
                    ("Pass", "Pass"),
                    ("CompileFail", "CompileFail"),
                    ("Fail", "Fail"),
                    ("Skip", "Skip"),
                ],
                db_index=True,
                max_length=16,
            ),
        ),
    ]
