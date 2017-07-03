# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-06-30 16:31
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('register', '0008_reimbursements'),
    ]

    operations = [
        migrations.AlterField(
            model_name='hacker',
            name='diet',
            field=models.CharField(choices=[('None', 'None'), ('Vegeterian', 'Vegeterian/Vegan'), ('Gluten-free', 'Gluten free')], max_length=300),
        ),
    ]