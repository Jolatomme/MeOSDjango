# Generated migration for score_race field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('results', '0008_composite_primary_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='competitionconfig',
            name='score_race',
            field=models.BooleanField(
                default=False,
                help_text='Classer les coureurs par points puis par temps en cas d\'égalité',
                verbose_name='course au score',
            ),
        ),
    ]
