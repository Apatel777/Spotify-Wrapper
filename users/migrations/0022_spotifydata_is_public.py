# Generated by Django 5.1.1 on 2024-11-23 23:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0021_alter_spotifydata_wrapper_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="spotifydata",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
    ]
